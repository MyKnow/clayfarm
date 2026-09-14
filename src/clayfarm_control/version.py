"""Single source of truth for the ClayFarm control-plane release version."""

# Bump this value for every user-visible feature or bug-fix release.  The
# package metadata is read from ``clayfarm_control.__version__`` so the CLI,
# API health response, manifests, and installed distribution cannot drift.
__version__ = "0.4.0.dev1"
