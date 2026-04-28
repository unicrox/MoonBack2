docker compose -f backend/docker/postgresql.yaml up -d
python3 backend/scripts/update_postgresql_schemas.py
