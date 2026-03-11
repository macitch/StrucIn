"""Single source of truth for the package version.

Both ``strucin.__init__`` and ``strucin.core.artifacts`` import from here to
avoid a circular-import cycle that would arise if ``artifacts`` imported
directly from the top-level ``strucin`` package.
"""

__version__ = "0.1.0"
