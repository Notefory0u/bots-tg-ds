from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def create_app(config_name=None):
    app = Flask(__name__)
    
    # Load configuration
    from config import config
    import os
    config_name = config_name or os.environ.get('FLASK_ENV', 'default')
    app.config.from_object(config[config_name])
    
    # Apply SQLAlchemy engine options if configured
    if hasattr(config[config_name], 'SQLALCHEMY_ENGINE_OPTIONS'):
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = config[config_name].SQLALCHEMY_ENGINE_OPTIONS
        
    db.init_app(app)
    return app
