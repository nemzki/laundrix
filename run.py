"""Entry point for running the app locally (python run.py).

Builds the Flask app with create_app() and starts the development server."""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
