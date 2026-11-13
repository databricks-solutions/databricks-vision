"""Post-deploy steps for scripts/post-deploy.sh: Lakebase bootstrap, UC grants, MLflow experiment.

Run through `run_py` in scripts/_common.sh (databricks-sdk + psycopg, no project venv):

    python3 scripts/deploy_helpers.py lakebase-bootstrap --endpoint ... --host ... --sp ...
    python3 scripts/deploy_helpers.py uc-grants --catalog ... --schema ... --sp ... --volume ...
    python3 scripts/deploy_helpers.py mlflow-experiment --name ... --artifact-location ... --sp ...

Auth: `WorkspaceClient()` resolves from the environment that _common.sh prepared
(DATABRICKS_CONFIG_PROFILE locally, or DATABRICKS_HOST + DATABRICKS_CLIENT_ID +
DATABRICKS_AUTH_TYPE=github-oidc in CI). Nothing here takes a token or profile argument.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound

REPO_ROOT = Path(__file__).resolve().parent.parent


def schema_sql() -> str:
    """Read `_SCHEMA_SQL` straight from the repo's image_gen.py (no import, so no stale
    installed copy and no runtime dependencies)."""
    tree = ast.parse((REPO_ROOT / "image_gen.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_SCHEMA_SQL" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise SystemExit("ERROR: _SCHEMA_SQL not found in image_gen.py")


# --- Lakebase ---------------------------------------------------------------------------


def lakebase_bootstrap(endpoint: str, host: str, sp: str) -> None:
    import psycopg
    from psycopg import sql

    w = WorkspaceClient()
    cred = w.postgres.generate_database_credential(endpoint=endpoint)
    role = sql.Identifier(sp)
    grants = [
        sql.SQL("GRANT ALL ON ALL TABLES IN SCHEMA public TO {}").format(role),
        sql.SQL("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {}").format(role),
    ]
    with psycopg.connect(
        host=host, dbname="databricks_postgres", user=w.current_user.me().user_name,
        password=cred.token, port=5432, sslmode="require", autocommit=True,
    ) as conn:
        conn.execute(sql.SQL("GRANT ALL ON SCHEMA public TO {}").format(role))
        conn.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {}").format(role))
        for stmt in grants:
            conn.execute(stmt)
        print(f"  Schema privileges granted to SP {sp}")

        # As the deployer, not the SP: only the owner can CREATE EXTENSION.
        conn.execute(schema_sql())
        print("  Schema bootstrap complete")

        for stmt in grants:  # cover tables the bootstrap just created
            conn.execute(stmt)
        print("  Table permissions ensured")


# --- Unity Catalog ----------------------------------------------------------------------


def uc_grants(catalog: str, schema: str, sp: str, volumes: list[str]) -> None:
    from databricks.sdk.service.catalog import PermissionsChange, Privilege, VolumeType

    w = WorkspaceClient()
    for volume in volumes:
        full = f"{catalog}.{schema}.{volume}"
        try:
            w.volumes.read(full)
            print(f"  Volume {full} exists")
        except NotFound:
            w.volumes.create(catalog_name=catalog, schema_name=schema, name=volume,
                             volume_type=VolumeType.MANAGED)
            print(f"  Created volume {full}")

    # securable_type is a lowercase string; privileges are Privilege enum members.
    w.grants.update(securable_type="catalog", full_name=catalog,
                    changes=[PermissionsChange(principal=sp, add=[Privilege.USE_CATALOG])])
    w.grants.update(securable_type="schema", full_name=f"{catalog}.{schema}",
                    changes=[PermissionsChange(principal=sp, add=[Privilege.USE_SCHEMA])])
    for volume in volumes:
        w.grants.update(securable_type="volume", full_name=f"{catalog}.{schema}.{volume}",
                        changes=[PermissionsChange(principal=sp,
                                                   add=[Privilege.READ_VOLUME, Privilege.WRITE_VOLUME])])
    print(f"  Granted USE CATALOG / USE SCHEMA and READ+WRITE on {len(volumes)} volume(s) to SP {sp}")


# --- MLflow -----------------------------------------------------------------------------


def mlflow_experiment(name: str, artifact_location: str, sp: str) -> None:
    from databricks.sdk.service.ml import ExperimentAccessControlRequest, ExperimentPermissionLevel

    w = WorkspaceClient()
    try:
        exp = w.experiments.get_by_name(name).experiment
    except NotFound:
        exp = None

    if exp is not None:
        exp_id = exp.experiment_id
        loc = exp.artifact_location or ""
        print(f"  Experiment exists (id={exp_id}, artifact_location={loc})")
        if not loc.startswith("dbfs:/Volumes/"):
            print("  WARN: the experiment's artifact_location is not a UC Volume, so trace attachments "
                  "will fail from the app. Use a fresh eval_experiment name so it is created on the Volume.")
    else:
        exp_id = w.experiments.create_experiment(name=name, artifact_location=artifact_location).experiment_id
        print(f"  Created experiment {name} (id={exp_id}, artifact_location={artifact_location})")

    w.experiments.update_permissions(
        experiment_id=exp_id,
        access_control_list=[ExperimentAccessControlRequest(
            service_principal_name=sp, permission_level=ExperimentPermissionLevel.CAN_EDIT,
        )],
    )
    print(f"  Granted CAN_EDIT on experiment {exp_id} to SP {sp}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("lakebase-bootstrap", help="Grant the app SP, bootstrap _SCHEMA_SQL, re-grant")
    p.add_argument("--endpoint", required=True, help="projects/.../branches/.../endpoints/...")
    p.add_argument("--host", required=True, help="Lakebase endpoint hostname")
    p.add_argument("--sp", required=True, help="App service principal client id")

    p = sub.add_parser("uc-grants", help="Create the app volumes if missing and grant the app SP")
    p.add_argument("--catalog", required=True)
    p.add_argument("--schema", required=True)
    p.add_argument("--sp", required=True)
    p.add_argument("--volume", action="append", required=True, dest="volumes")

    p = sub.add_parser("mlflow-experiment", help="Get-or-create the eval experiment and grant the SP")
    p.add_argument("--name", required=True)
    p.add_argument("--artifact-location", required=True)
    p.add_argument("--sp", required=True)

    args = parser.parse_args(argv)
    if args.command == "lakebase-bootstrap":
        lakebase_bootstrap(args.endpoint, args.host, args.sp)
    elif args.command == "uc-grants":
        uc_grants(args.catalog, args.schema, args.sp, args.volumes)
    elif args.command == "mlflow-experiment":
        mlflow_experiment(args.name, args.artifact_location, args.sp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
