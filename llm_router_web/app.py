# The heavy lifting is now inside the `web` package.
from web import create_app

if __name__ == "__main__":
    # Create the Flask app with all extensions, models, routes, etc.
    app = create_app()
    # Use the same host / port as before.
    app.run(host="0.0.0.0", port=8081, debug=True)
