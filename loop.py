import sys, os, time, schedule
sys.path.append(os.path.dirname(os.path.realpath(__file__)))

# Import the centralized configuration
from config.settings import Settings, initialize_settings

# Initialize settings first
initialize_settings()

from app.views import loop_strategy

def main():
    from app import create_app
    app = create_app()
    app.app_context().push()
    loop_strategy()

if __name__ == '__main__':
    main()  