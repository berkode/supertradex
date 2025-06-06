from web.app import create_app
from config.settings import Settings, initialize_settings
import os

# Initialize settings
initialize_settings()

# Get settings instance
settings = Settings()

# Create Flask application
app = create_app()

if __name__ == "__main__":
    # Get port from environment variable or use default
    port = int(os.environ.get("PORT", 5000))
    
    # Run the application
    app.run(
        host="0.0.0.0",
        port=port,
        debug=settings.LOG_LEVEL == "DEBUG"
    ) 