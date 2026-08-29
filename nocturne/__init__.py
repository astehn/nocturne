__version__ = "0.20.0"
APP_NAME = "Nocturne"
APP_TAGLINE = "Guided astrophotography processing for smart-telescope stacks"

# Nocturne is beta and every surface that names the app must say so. Until
# 2026-08-23 exactly none of them did — "beta" appeared nowhere in the package,
# the README or the changelog, only on the website — so a user's own machine
# never told them. Andreas: "the main purpose is to make sure that no one
# misses that this is beta software."
#
# ONE definition, because the alternative is four copies drifting apart at the
# next release; tests assert each surface derives from here rather than
# spelling it out again. Set RELEASE_STAGE to "" to ship a stable release and
# every surface drops the marker at once.
RELEASE_STAGE = "beta"
# NOTE: the splash ARTWORK (nocturne/assets/splash.png) also sets the word
# "Beta" in its own type, and no code can clear that. Clearing RELEASE_STAGE for
# a stable release therefore needs the image swapped by hand as well. The app's
# own surfaces -- window title, About, README -- all derive from the constant
# and drop the marker on their own; the picture does not.

# Names the real risk instead of saying "expect bugs". This is not boilerplate:
# a defect found on 2026-08-23 let Batch overwrite the very master it was
# reading, and this sentence is the advice that would have saved that file.
BETA_NOTICE = "Expect rough edges — keep your originals backed up"


def version_label() -> str:
    """"0.17.0 (beta)" while RELEASE_STAGE is set, "0.17.0" once it is not."""
    return f"{__version__} ({RELEASE_STAGE})" if RELEASE_STAGE else __version__


def app_title() -> str:
    """"Nocturne 0.17.0 (beta)" — the window bar's base, shared so the title
    and the About dialog can never disagree about what is running."""
    return f"{APP_NAME} {version_label()}"
