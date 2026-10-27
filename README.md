# Campus Bites

Campus Bites is a small food-review site for discovering places to eat around campus. Browse a ranked list of restaurants, read reviews and rating breakdowns, and register to leave or edit one review per restaurant.

Restaurant listings and sample reviews are fictional starter data. New accounts and reviews are stored in SQLite.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

Open <http://127.0.0.1:5000>. The app creates `instance/campus_bites.db` and seeds the sample restaurants on first run. Set `DATABASE_PATH` to use a different SQLite file and `SECRET_KEY` to a long random value before deploying.

## Deploy to Cloud Run

With Google Cloud CLI installed, authenticated, and a project selected:

```bash
gcloud run deploy campus-bites --source . --region us-central1 --allow-unauthenticated \
  --set-env-vars SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
```

Cloud Run's container filesystem is ephemeral. This SQLite setup is suitable for local development and a single-instance demonstration, but its database may be lost when Cloud Run replaces an instance. For durable production data, connect the app to a managed database or mount persistent storage and set `DATABASE_PATH` accordingly.
