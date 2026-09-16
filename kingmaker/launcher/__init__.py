"""The launcher: the window that starts and stops the server for whoever
does not want a terminal.

`core` is everything that can be tested without a screen — settings, the
child process, the lines it prints, the update check, the lock; `window`
is the tkinter around it. Nothing here imports `kingmaker.state` or the
interface: the launcher is a separate process from the game, and must stay
light and unable to touch the save except through the server it starts.
"""
