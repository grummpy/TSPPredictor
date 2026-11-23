"""Optional data connectors and plugins.

Every connector is off until configured: network connectors need an explicit
CLI command (and ALFRED an API key in the environment); optional libraries are
used only when installed.  Nothing here runs during ``tsp build`` unless its
cached output already exists on disk.
"""
