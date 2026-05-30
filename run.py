"""Entry point for LINE stamp web app."""

from app import create_app

app = create_app()

if __name__ == "__main__":
    # use_reloader=False prevents Flask from restarting mid-generation when files change
    app.run(debug=True, use_reloader=False, port=5000)
