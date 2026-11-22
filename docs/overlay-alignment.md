# Simulation overlay alignment

| Overlay | Anchor and rendering | Visibility |
|---|---|---|
| Gripper lines and spheres | MuJoCo draws the line along the fingers' opening axis, centered on the live TCP. A smaller sphere and connector identify the commanded goal when it differs from the TCP. | Dashboard → Control |
| Gripper coordinates and hit areas | Browser labels and pointer targets use the TCP projected from the camera of the displayed JPEG. The label's text is offset for readability. | Dashboard → Control |
| Object handles | Browser dots sit 12 mm above the top of the collision bounds. The projected bounds center also provides a body hit area. MuJoCo draws the drop line and shadow under a held object. | Handles in Dashboard → Objects. A held object's drop marker lasts until release. |
| X-Ray paths and markers | MuJoCo draws planned TCP positions from a real or scripted action chunk, its endpoint, and the commanded open/close point. The target sphere uses the position captured with that plan. Historical plans without a recorded fixed-container position omit that sphere. | Any visible live preview when the overlay is enabled and a plan is available. |
| Scene zones | MuJoCo draws the success zones at the current containers and the task guide from a point 6 cm above the object to the target. | Any visible live preview when success zones are enabled. |
| Run badge, caption and interaction hints | Browser elements anchored to the viewport. | Any visible live preview. |
| X-Ray camera thumbnails and heatmaps | Saved camera frame and analysis from the same snapshot. Heatmap cells are shown in that camera's image coordinates. | X-Ray results. |
| Test Suite and Fork Here historical evidence | Captured robot-camera images and timestamps are loaded with their recorded run. Fork Here compares events and outcomes. | Report and Fork Here. Live decorations are separate from saved frames. |

Build and the optional simulation preview in Report display the shared live image. They hide Dashboard's Control and Objects panels. Opening Fork Here does not create a new viewer or attach overlays to a saved snapshot.

To check the fix in Waterfox, open `http://localhost:8012/`, hard-refresh, and choose **Dashboard → Control**. Drag a blank part of the image to orbit. Shift-drag empty space to pan, wheel over empty space to zoom, then double-click empty space to reset the camera. Use **Rotate** to change the dashboard layout and click the center of a colored gripper sphere to pick it. Choose **Objects** to repeat with a handle above a fruit. The **Offline demo** button runs motion without API requests.

A browser frame and its projected state arrive together. The browser paints the image and moves the labels in the same update. Drawing and hit-testing use the same contained-image box in CSS pixels. Drag commands send the displayed frame ID so the simulator can unproject with that frame's camera. The automated renderer reference uses the centroid of a rendered sphere and a two-pixel tolerance at three render sizes.
