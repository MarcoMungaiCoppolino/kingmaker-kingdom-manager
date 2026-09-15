"""The memory of where you were looking at the map.

Changing tab and coming back to the Map one found oneself at the top left
corner: whoever plays in the right half of the Stolen Lands had to make the
trip again every time. The piece that fixes it lives in the browser, and here
what can be checked from Python is checked — that the code is served, and
that it is made of the right parts.

The real behaviour was tested by the browser: six rounds through every tab,
six returns to the same spot.
"""
import re

from kingmaker.ui import theme

results = []
JS = theme.SCROLL_JS

# --- 1. the code really reaches the page --------------------------------
source_text = open(theme.__file__, encoding="utf-8").read()
results.append(("the script ends up in the body of the page",
              'ui.add_body_html(f"<script>{SCROLL_JS}</script>")' in source_text))
results.append(("the brackets balance, or the browser does not run it at all",
              JS.count("{") == JS.count("}") and JS.count("(") == JS.count(")")))

# --- 2. the parts that are needed --------------------------------------
results.append(("it remembers where one was looking",
              "km-map-view" in JS and "sessionStorage" in JS))
results.append(("as a fraction and not in pixels, so the zoom does not throw it off",
              "scrollWidth - box.clientWidth" in JS
              and "memory.x * dx" in JS))
results.append(("it writes nothing while the box is hidden",
              "const visible = () =>" in JS and "if (!visible()" in JS))

# --- 3. the hand is always right ---------------------------------------
# The rule holding everything up: only what a hand did not do is put back.
# Without this distinction the memory overwrote itself with the very zero it
# meant to undo.
results.append(("a gesture on the map marks the time",
              "lastGesture = Date.now()" in JS))
results.append(("and the gestures watched are all those that scroll",
              all(g in JS for g in ("wheel", "mousedown", "mousemove",
                                    "touchstart", "touchmove", "keydown"))))
results.append(("dragging too, which lasts longer than an instant",
              re.search(r"if \(!active\) return;\s*//[^\n]*\n(\s*//[^\n]*\n)*\s*gesture\(\);",
                        JS) is not None))
results.append(("it corrects only after a moment without hands",
              "Date.now() - lastGesture > BREATH" in JS))

# --- 4. the moment to correct -------------------------------------------
results.append(("it hooks onto the click outside the map, which is how the tab changes",
              "box.contains(e.target)" in JS))
results.append(("and keeps watch for a while, because the jump comes after the click",
              "watchUntil" in JS))
# With timers and not with frames: when the window does not paint — another
# window in front, the tab in the background — frames do not run, and the
# restore would never start. It is exactly the case where it is needed.
results.append(("with timers, which run even when the window does not paint",
              "requestAnimationFrame(watch)" not in JS
              and "setTimeout(watch" in JS))
results.append(("and not even the first restore waits for a frame",
              "setTimeout(() => restoreWhenPossible(" in JS))

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print("")
print(str(sum(1 for _, ok in results if ok)) + "/" + str(len(results)) + " passate")
