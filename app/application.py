"""Flask application factory."""
from flask import Flask
from app.config import HOST, PORT
from app.views.health import bp as health_bp
from app.views.research import bp as research_bp
from app.views.analytics import bp as analytics_bp
from app.views.nl_search import bp as nl_search_bp
from app.views.relationship import bp as relationship_bp
from app.views.lineages import bp as lineages_bp


def create_app():
    app = Flask(__name__)
    app.register_blueprint(health_bp)
    app.register_blueprint(research_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(nl_search_bp)
    app.register_blueprint(relationship_bp)
    app.register_blueprint(lineages_bp)
    return app


# For gunicorn: gunicorn app.application:app
app = create_app()


def run_app():
    app.run(host=HOST, port=PORT, debug=True)


if __name__ == "__main__":
    run_app()
