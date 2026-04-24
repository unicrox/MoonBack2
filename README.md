# MoonBack

MoonBack is an early-stage project for building a local full-stack AI application.

It is based on the idea that people and AI can work together to build software.

The goal is to bring the backend, frontend, AI logic, and local runtime together in one place, making it easier for people and AI to build, understand, and improve the system together.

## Project Structure

```text
MoonBack2/
├── backend/
│   ├── api/                  # FastAPI routes
│   ├── core/                 # config, security, startup logic
│   ├── schemas/              # data schemas for API and database
│   ├── services/             # business logic
│   ├── main.py               # FastAPI entry point
│   ├── tests/
│
├── ai/
│   ├── agents/               # AI agents and workflows
│   └── tools/                # AI callable tools
│
├── frontend/
│   ├── src/
│   │   ├── app/              # React app setup
│   │   ├── components/       # shared UI components
│   │   ├── pages/            # app pages/views
│   │   ├── features/         # feature modules
│   │   ├── lib/              # API client, helpers
│   │   └── styles/           # global styles/theme
│   ├── public/
│
├── runtime/
│   ├── desktop/              # local app shell, Electron/Tauri/etc.
│   ├── scripts/              # start/build/package scripts
│   └── config/               # local runtime config
│
├── _docs/
│
├── _dev_prompts/
```

## Status

This project is still in progress. The structure, features, and implementation will change as it develops.

## License

MIT License.
