# Recording Matched Controls

A control gives a baseline for deciding whether a feature could be explained by the scene, camera, processing, or optics.

## A useful starting setup

- Securely mount a laser pointing at a non-reflective wall or target with an appropriate beam stop. Follow applicable laser safety practices and use trained handling.
- Fix the camera position, focus, exposure, white balance, zoom, frame rate, resolution, and recording codec where possible.
- Record the main optical configuration, and a **matched control** that changes only the variable you plan to test. For example, compare with and without an intermediate optical layer when the change can be made safely.
- Log laser wavelength and reported class/power if known, projected pattern, target surface, room lighting, camera details, distances, and any saturation.
- Repeat controlled captures across sessions; preserve originals and note any conversion or processing.

A different phone, dark-room clip, or unrelated online laser video is not automatically a matched control. LaserLab's bundled fixtures are for testing the software, not evidence about your personal setup.

## Common quality problems

**Clipped or saturated beam:** white-hot pixels can create artificial edges. Reduce exposure safely or improve capture conditions; never increase exposure by observing the beam directly.

**Changing multiple things at once:** if the camera, wall, exposure, and optics all change, it is difficult to know which change caused a score difference.

**Moving camera:** handheld footage can inflate structure/persistence measurements. Use a stable mount when possible.

**A few frames:** small demonstrations are useful for software smoke tests, not robust research conclusions.

## Safety

Never view a beam directly, point it at people, operate at eye level, or aim at reflective surfaces. Class/power labels entered into the app are not verified safety measurements. The project does not provide instructions for drug use or unsupervised human-subject experimentation.

See [Understanding Results](Understanding-Results.md) for what the analysis can conclude.
