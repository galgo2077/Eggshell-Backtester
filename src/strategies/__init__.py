import os
import sys

# Add the submodule to sys.path so its contents can be imported directly
submodule_path = os.path.join(os.path.dirname(__file__), "Strategies-eggshell")
if submodule_path not in sys.path:
    sys.path.insert(0, submodule_path)

# Import the actual packages from the submodule
import Elliot_bollinger
import Ema_cross

# Expose them as if they were submodules of the `strategies` package
sys.modules['strategies.Elliot_bollinger'] = Elliot_bollinger
sys.modules['strategies.Ema_cross'] = Ema_cross
