# Deploy TripMate AI on Render and Neon

This guide deploys the FastAPI app as a Docker Web Service on Render and uses Neon for persistent PostgreSQL conversation state.

## 1. Create the Neon database

1. Create a project at [Neon](https://neon.com/).
2. Choose a region close to the Render service region you plan to use.
3. In the Neon dashboard, open **Connect** and copy the direct PostgreSQL connection string for the default database and role.
4. Keep the connection string private. You will add it to Render as `DATABASE_URL`; do not commit it to Git or paste it into an issue or chat.

The application adds `sslmode=require` to `DATABASE_URL` when it is not already present.

## 2. Confirm the GitHub repository

Render deploys from the connected Git repository. Confirm the deployment files are on the branch you intend to deploy (this project uses `main`):

- `Dockerfile`
- `app.py`, `backend.py`, and `mcp_client.py`
- `requirements.txt`
- `templates/` and `static/`

Push any deployment changes to GitHub before creating the Render service. Subsequent pushes to the selected branch can trigger automatic deployments.

## 3. Create the Render Web Service

1. In the [Render dashboard](https://dashboard.render.com/), select **New** > **Web Service**.
2. Connect the GitHub repository and grant access if prompted.
3. Configure the service:

   | Setting | Value |
   | --- | --- |
   | Branch | `main` (or the branch you deploy) |
   | Runtime | Docker |
   | Root Directory | Leave blank (repository root) |
   | Dockerfile Path | `./Dockerfile` |
   | Region | Use the same or a nearby region to Neon |
   | Health Check Path | `/health` |

4. Choose the Free instance for a demo, or a paid instance for an always-on service with more resources.
5. Add the environment variables from the next section before the first deploy.
6. Create the Web Service and wait for the image build and deployment to complete.

The Dockerfile installs `uv`, which provides the `uvx` command used to launch the AviationStack MCP server. It also listens on Render's injected `PORT`, with port `8000` as the local default. Do not set a separate `PORT` variable in the Render dashboard.

## 4. Add Render environment variables

In the Render service, open **Environment** and add:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Neon direct PostgreSQL connection string |
| `GROQ_API_KEY` | Groq API key |
| `TAVILY_API_KEY` | Tavily API key |
| `AVIATIONSTACK_API_KEY` | AviationStack API key (no underscore between `AVIATION` and `STACK`) |
| `OPENWEATHER_API_KEY` | OpenWeather API key |
| `DEFAULT_ORIGIN_IATA` | Optional; defaults to `DAC` |

Enter values without surrounding quotes. Treat API keys and the database URL as passwords: keep them in Render's environment settings, never in source control. Save the changes and redeploy if Render does not start a deployment automatically.

## 5. Verify the deployment

1. In Render, open **Logs** and wait for the service to start.
2. Confirm the logs say `Using PostgreSQL checkpointer.` This means the app connected to Neon and initialized its checkpoint tables.
3. Open the service URL in a browser. The planner page should load.
4. Open `https://YOUR-SERVICE.onrender.com/health`; expect a JSON response with `"status": "ok"`.
5. Submit a short test travel request and watch the run console for phase updates.

The health endpoint only checks that the web app is running; it does not test database connectivity. The backend catches database startup errors and falls back to an in-memory checkpointer. If logs instead say `PostgreSQL unavailable; using in-memory checkpointer`, fix `DATABASE_URL` and redeploy. In-memory conversations are not durable and disappear when the service restarts.

## 6. Free-tier behavior and troubleshooting

- Render Free Web Services spin down after inactivity, so the first request after a quiet period can take about a minute to start.
- Neon Free compute scales to zero after inactivity. The first database operation after it sleeps can also be slower.
- Free plans have resource and usage limits and are intended for demos, not production guarantees. Check the current [Render free-instance limits](https://render.com/docs/free) and [Neon plan limits](https://neon.com/pricing).
- The app calls Groq, Tavily, AviationStack, and OpenWeather. Hosting may be free while those providers still enforce their own API quotas or charges.
- If startup fails because `GROQ_API_KEY` is missing, add it in Render's Environment settings and redeploy.
- If flight or MCP calls fail, check the deployment logs and verify the corresponding API key is valid. An invalid AviationStack key does not prevent the page from loading, but flight data will be unavailable.
- If the image build fails, inspect the Docker build logs first. The Docker service must build the repository's root `Dockerfile` so that `uvx` is installed along with the application dependencies.