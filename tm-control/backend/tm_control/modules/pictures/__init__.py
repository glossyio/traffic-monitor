"""Reference pictures kept on the device: two frames per picture under the state directory and a row in `pictures`.

The module's Module is in router.py, not here: the Cameras router imports the picture's answer from there, and the
store imports the cameras package, so importing the router here would make the packages import each other.
"""
