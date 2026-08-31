# Changelog

All notable changes to Nocturne. This project uses [semantic versioning](https://semver.org/); while pre-1.0, minor versions add features.

## [0.21.0] — 2026-08-31

The app could never reach the internet — and a toolbar ordered around how you actually work

### Added
- Trim has the framing controls Crop has always had. An Aspect ratio box locks the box to a fixed shape and Guides draws the rule of thirds or a centre cross inside it, so a late trim can be composed rather than merely eyeballed. Both default to off, so trimming a few pixels off one edge works exactly as before.
- Compressed FITS files open. A tile-compressed file (often .fits.fz, and what several capture programs and archives hand out) keeps its image in a different place inside the file, and Nocturne only ever looked in the first — so those files could not be opened at all.

### Changed
- The toolbar is ordered by when a session reaches each tool, its icons are tinted by group so related tools read as a set, and About has gone — it was a button spending permanent space on something you look at once.
- The GraXpert / RC-Astro / ASTAP checkmarks have moved into Settings. They sat in the toolbar reporting good news forever; now the toolbar speaks only when a tool is configured but broken.

### Fixed
- Nocturne could not make a secure connection at all once built. Certificates were resolved against the machine the app was built on, so on any other Mac every attempt failed silently. The update check has therefore never once told anyone about a new version, and SPCC's star-catalogue lookup was failing the same way. Certificates now travel with the app, and a release is blocked if the built app cannot make a connection.
- Aspect ratios 1:1 and 4:5 did nothing on a landscape image — which is every Seestar frame. Choosing them left the box exactly as it was, in Crop and in Share. Changing your mind about a ratio also no longer shrinks your selection.
- The Export step no longer shows a greyed-out "Next →". It is the last step, and a disabled Next reads as something you have failed to do.
- Upscale no longer shows an Engine dropdown containing a single choice.

## [0.20.0] — 2026-08-29

Ha/OIII extraction, rebuilt — and a way to use what it makes

### Added
- Combine Ha + OIII, a new tool. Give it a stacked Ha file and a stacked OIII file and it builds the same kind of two-gas master the extractor makes, ready for the normal steps. The files can come from Nocturne or from anywhere else — another program, a mono camera, someone else's data — so channels Nocturne could not open at all are now something it can process. A Balance slider decides how much to lift the oxygen toward the hydrogen while the data is still linear, which is the one thing you cannot do after a stretch, and a live preview shows the result as you move it. If the two files do not line up it says how far apart they are and offers to align them.
- Ha/OIII can write each gas as its own file. Off by default; tick Also write separate Ha and OIII files and you get a mono Ha and a mono OIII beside the master, left un-equalised so the true ratio between the two gases survives for whoever recombines them.
- Ha/OIII gained the controls Stack has always had: Strictness, Framing (trim the ragged edges, or keep the full frame), a frame preview — click any row to see that sub — and a Verdict column that says why a frame was left out instead of leaving you a row of zeros. Rejected rows are dimmed, and a frame kept with a caveat is amber.
- Ha/OIII can be stopped. A 1,116-frame extract runs for a long time and there was no way out of it; grading is interruptible too.
- The Ha/OIII dialog explains itself. It had no descriptive text and not one tooltip, which is why it was possible to commission the tool and still not know what subs it takes or what to do with the result.

### Changed
- Ha/OIII is 8.7x faster. Both gases now travel through one pass over the frames instead of one pass each, and registration runs across processes as the normal stacker has since v0.16.0. On 80 real subs a run went from 48.0 s to 15.4 s.
- The oxygen channel is 35% stronger. Green and blue both measure the same oxygen line, and they were averaged evenly despite green coming from twice as many sensor pixels and measuring the line better. Weighting them by how well each actually sees it is worth 26% on its own.
- An Ha/OIII master now names its camera, its filter and whether it was trimmed. It carried none of that, so a master loaded back in could not say what took it, and two masters of the same subs could differ in size by half with nothing on disk to say why.
- The Ha/OIII help no longer claims that ordinary stacking mixes the two gases together. That is the standard argument for this kind of tool and it is true of most programs, but not of Nocturne, which debayers in a way that never looks across colours. What the tool actually gives you is the two gases brought to a comparable level while the data is still linear.

### Fixed
- The two gases came out about a pixel apart. Red, green and blue sit at different places in the sensor's colour grid, and each was being put back as though they sat in the same place. Every star carried a faint colour fringe and the master was softer than it should have been. Fixing it also made the hydrogen channel slightly sharper and cleaner than a normal stack of the same frames.
- Field rotation was being drawn onto the picture. An untrimmed Ha/OIII master came out with bright wedges across it where a normal stack of the same subs was clean: frames were never brought to a common sky level, so every coverage boundary became a step in brightness. It was invisible for as long as the tool always cropped to the middle.
- Ha/OIII and Stack framed the same subs differently, because they chose different reference frames. Ha/OIII picked by overall score, which favours a frame with many stars over a sharp one — on a night when transparency varies that can align a whole session to a soft frame.
- The Ha/OIII window wasted its space when maximised: one line of text was given 237 pixels while the frame list and preview were squeezed into 238.
- Wide-gamut colour profiles work when exporting Starless + Stars, which are 16-bit TIFFs like any other and were being refused one.

## [0.19.0] — 2026-08-27

Star Spikes, Narrowband and Colour Balance, gone over control by control

### Added
- Narrowband has a Tame core slider. A bright nebula core often comes out of the palette combine close to white with its colour squeezed out; this rolls those highlights back down so the colour underneath shows. On a 30-minute Pacman master it takes the near-white share of the core from 6% to 2%. It was in the engine all along, sitting at a value that did nothing, with no control able to reach it. Off by default, so nothing you have already made changes.
- Star Spikes has Variation and Star colour. Real diffraction spikes are never identical: Variation gives each star its own arm length, angle and brightness, and lets the four arms differ from one another, so a field of them stops looking stamped. Star colour carries each star's own hue into its cross — a bright star's core is blown white in every channel, so the colour is now read from a ring around it instead of its centre.
- Compare with original in all three dialogs — Narrowband, Star Spikes and Colour Balance. Splits the preview against the image you opened with, using the same draggable divider as the main window's Before/After. A recolour or an effect is hard to judge against nothing.
- Star Spikes has a Reset, and finds its stars without freezing the window while it opens.

### Changed
- The clipping warning now says which colour channel died, and the overlay is coloured by it. It reads "6.6% of red crushed to zero" rather than "6.6% shadows (R)", and a mark's colour tells you which channel is gone — red, green or blue for one, yellow, magenta or cyan for two, white for all three, which is the only case where the pixel really is black. The measurement was always per channel; nothing said so, so checking whether the pixel looked black tested the wrong thing.
- Star Spikes picks its stars far better. It ranked them by total light, which let a diffuse patch of nebula outrank a genuinely bright star and get a cross drawn on it — the largest such patch on a real master was 5,099 pixels. It now ranks by brightness and discards anything not shaped like a star, and the count slider will not offer more stars than the image holds.
- Narrowband's Green blend is greyed out in Pseudo-SHO and Pseudo-bicolor, where it never did anything. Those palettes take green straight from one gas, so the slider moved and the picture did not. Your setting is kept and applies again in HOO.
- The Narrowband palette list explains itself. Each palette now says what it does to each gas — hydrogen red and oxygen teal in HOO, gold and blue in Pseudo-SHO, magenta and green in Pseudo-bicolor — rather than leaving three names to guess at.

### Fixed
- Narrowband's Apply froze the window for up to eight seconds on a large master, with nothing on screen to say why. It now runs in the background and says what it is doing.
- Narrowband's Saturation slider barely touched the nebula core — the part you are usually trying to colour. The boost was being tapered away from bright areas to protect star colour, on a layer whose stars had already been removed. On a real master the core now responds half again as strongly.
- Narrowband's Protect background traced a hard edge around the nebula. The boundary followed the noise pixel by pixel; it is now softened, which removed every one of the 300,000 places where the mask jumped in a single step.
- Narrowband produced a different image from a recipe or a Batch run than it did by hand, because the tool and the engine disagreed about whether Preserve lightness starts on. They now cannot disagree.
- Star Spikes drew its crosses slightly beside the stars rather than on them — up to three pixels off, against arms less than one and a half pixels thick. It now finds each star's centre to a fraction of a pixel.
- Star Spikes said nothing at all when an image had no stars in it: four sliders that moved and did nothing, with no way to tell a broken tool from an image with nothing to work on. It now says so.
- Colour Balance could save an image built from settings you had already changed. Apply runs in the background, and the sliders stayed live while it worked, so nudging one during the seconds it takes on a large mosaic changed what was written — and the settings recorded in the log and the provenance report were read even later than that. Everything is now captured the moment you press Apply, and the controls are held while it runs.
- The Narrowband panel cut off the end of its own text — the palette description was sliced mid-sentence and "Preserve lightness" lost its last word.

## [0.18.0] — 2026-08-25

A beta that says so, a Batch that cannot overwrite your masters, and help that matches the app

### Added
- Nocturne now tells you it is beta. A launch splash carries the logo and the beta marker, and the version reads as beta everywhere it is shown. The word had appeared nowhere on your own machine before — only on the website — so nothing in the application itself ever said what stage it is at.
- Batch checks your recipe against the tools you have installed before it runs, and says which one is missing. A recipe containing Background needs GraXpert; without it every file in the folder used to fail in turn, under an error that never mentioned GraXpert. Recipes that do not use Background are unaffected — every other tool-backed step falls back to a free implementation and runs fine without RC-Astro.

### Changed
- Seven help topics rewritten against the dialogs that actually exist: Ha/OIII, Narrowband, Dualband, Recipes & Batch, Star Spikes, Upscale Crop and Auto Enhance. The Ha/OIII topic described a tool that is not in the application, the Recipes & Batch topic named none of its controls, Star Spikes gave neither a default nor a range for any of its sliders, and Auto Enhance promised a plan it does not always run.

### Fixed
- The Starless + Stars export was locked to sRGB. Both files it writes are 16-bit TIFFs, so they can carry Display P3, Adobe RGB or ProPhoto RGB exactly like any other 16-bit export — the colour space list simply refused to offer them.
- Batch could write an export straight over the file it had just read. With the output folder set to the input folder and the format set to FITS, each processed image overwrote its own source. A stacked master is hours of capture, and there was no prompt and no undo.
- Batch reported "Done — 0/0 succeeded" when pointed at a folder holding nothing it can read, which reads as success. It now refuses before starting and names both the folder it searched and the extensions it searched for — which also covers images sitting one level further down, since it does not search subfolders.

## [0.17.0] — 2026-08-20

Colour-managed exports, a proper Curves editor, and setup that configures itself

### Added
- Choose the colour space on export — sRGB, Display P3, Adobe RGB or ProPhoto RGB. The image is converted into the space you pick and the ICC profile is embedded, so Photoshop and Lightroom read it as what it is instead of assuming their own working space. Wide-gamut spaces on 16-bit TIFF.
- A large Curves editor, over three times the area of the side panel, with the live preview beside it.
- Six Curves presets — Add contrast, Strong contrast, Lift faint, Deepen sky, Tame highlights — each measured against your own image rather than a fixed shape, so the background stays put while the rest of the curve moves.
- Curves now draws your histogram behind the grid, with black-to-white ramps along both axes so you can see which tones you are moving.
- Nocturne finds GraXpert, RC-Astro and ASTAP where their installers put them, so a fresh install usually needs no setup at all — and a Rescan button repairs a path that has been typed wrong.

### Changed
- Auto Levels now sets a black point and nothing else. It had been re-brightening midtones on top of a stretch that already placed the background, lifting the sky 12–30% and washing images out.
- GraXpert denoise strengths recalibrated against real data: medium is 14% quieter and 36% cleaner in colour, at the same runtime.
- The Levels black point adjusts in thousandths rather than hundredths — it is the value Auto sets, and hundredths rounded most of the adjustment away.

### Fixed
- Every Browse button in Settings did nothing, in every release since v0.12.0. Configuring GraXpert, RC-Astro or ASTAP by hand-typed path was the only route left.
- A tool path pointing at a file that cannot be run — a document, a folder — was reported as installed with a green checkmark.
- Exports carried no colour profile at all, so other editors guessed and could render a correct file far too dark.
- Auto Levels did nothing to the shadows of any mosaic: its black point read the empty border and came out as exactly zero.
- Auto Levels clipped roughly 6,000 star cores to pure white on a typical frame, throwing away their colour.
- The Open large editor button in Curves did nothing.

## [0.16.0] — 2026-08-19

Stacking is seven times faster.

### Changed
- Stacking is about seven times faster. A 266-frame Pleiades stack that took ten minutes now takes under a minute and a half. Nocturne was using one processor core out of fourteen; it now uses your machine properly, and it works out how hard to push from the machine it finds itself on rather than from a fixed number — so a laptop is never asked to do what a desktop can, and a desktop is not held back to what a laptop could manage. The finished master is identical to the pixel, so saved projects reproduce exactly as they did before and nothing you have already made changes.

### Fixed
- A finished mosaic now opens in the editor, the same as any ordinary stack. It used to complete and then go nowhere — you had to close the stacking window and open the file by hand. It had been that way since mosaics arrived.

## [0.15.0] — 2026-08-18

Colour you can steer, and stacks that stopped blurring themselves.

### Added
- Green ↔ Magenta and Cool ↔ Warm sliders on the Colour step. After you calibrate — sky balance or photometric — two sliders shift the overall colour of the picture, with a live preview as you drag and their own Apply. Both sit at zero and change nothing until you move them; double-click either to re-centre it. They multiply the colour channels rather than clamping one of them down, so the differences between stars survive the adjustment: an orange star stays orange next to a blue one, which is the one thing Remove Green cannot promise. Seestar data tends to land slightly magenta — measured at the same amount in a single raw frame as in a finished stack, so it comes from the camera rather than from the stacking — and a small nudge toward green is usually all it wants. The panel now runs in the order you would actually work in: calibrate, nudge to taste, then remove green only if you imported the image from other software, which is where a green cast normally comes from.
- Opening a saved project shows progress instead of appearing to freeze.

### Changed
- Stacks are sharper. Registration was resampling every frame with bilinear interpolation, the softest option available, which set a floor on how sharp any stack could be. Measured on 266 frames of the Pleiades, moving to bicubic recovered 4.5% of star sharpness with no artefacts. A sharper demosaic was tried alongside it and rejected: it measured 21.7% sharper again, but painted a four-fold coloured cross around every star, and filtering that out bleached the real colour from the stars before it removed the artefact.
- Colour Balance opens faster — the star separation is reused between opens rather than recomputed each time.

### Fixed
- Stretch committed something different from what you were looking at. Pressing Apply without touching the slider changed the picture: 94.7% of pixels moved and the mean brightness rose 8.9%.
- The image no longer moves as you step through the pipeline. The right-hand panel changed width from one step to the next, shifting the picture under your cursor; it now holds a fixed width.
- Stacking registers against the sharpest frame rather than the highest-scoring one. Star count was swamping sharpness in the score, so on a night of varying transparency a hazier but star-rich frame could be chosen as the reference every other frame was aligned to. On a Milky Way set this took the finished master from 2.95 to 2.14 FWHM.
- Colour calibration now says which failure it hit — Gaia unreachable, no usable stars, or an unreadable answer — instead of reporting all three as "Couldn't reach Gaia", which sent people looking at their network for faults that were not there.

## [0.14.0] — 2026-08-17

Colour work that no longer needs another program.

### Added
- Colour Balance, a new finishing tool on the toolbar. Shift the colour of one tonal range at a time, inside a band of brightness you choose. Shadows, midtones and highlights each keep their own three sliders — Cyan/Red, Magenta/Green, Yellow/Blue — so you can warm the arms of a galaxy and leave its golden core alone in a single adjustment. The band is set with two handles over the image's own histogram, with a black-to-white scale beneath them so it is clear what is being selected, and the presets are measured from your picture rather than being fixed numbers: a stretched sky sits wherever the stretch put it. Tick Show the mask and the areas that will change light up in their own colours while everything else dims, so you can see exactly where the adjustment lands rather than only how strong it is. Your stars are separated out, left completely untouched, and laid back on top. It is a finishing tool, so it appends to your history and never discards work you have already done — run it twice with different settings if you want to treat two parts of the picture differently.
- Black and white points on the Curves editor. Both end handles now drag: pull the low one right to set a black point, the high one left to set a white point. That is the commonest move there is on a curve and it was previously impossible — the corners were pinned. Click any point to see its input and output, and nudge it with the arrow keys one 8-bit level at a time, or ten with Shift.

### Changed
- Colour Balance skips the pixels its mask discards, which took Apply on a 39.5 megapixel mosaic from 7.6 seconds to 3.4, and it now composes off the interface thread so the window stays responsive while it works.

### Fixed
- Open Project could not open a project. It raised an error instead of opening anything, and had done since v0.12.0 — two releases. The cause was a change to how file dialogs are opened: the new one returns a path where the old one returned a path and a filter, and the caller was still expecting both.
- The Colour Balance and Narrowband previews were throwing away most of the star field when shrinking the image for display, taking every thirteenth pixel rather than averaging. Measured on three hundred synthetic stars, two hundred and fifty-three disappeared entirely and the survivors were drawn at full brightness — which is why stars looked blocky when you zoomed in. Both now average, so every star survives.
- The Narrowband preview showed the starless layer, with the stars only added back when you pressed Apply. What you were tuning against was never what you got.
- Curves mishandled a lifted black point, crushing the very shadows it was meant to lift. The curve carried on past its outermost control points instead of holding their values, so raising the black point returned something darker than the point itself.

## [0.13.0] — 2026-08-16

Mosaics, and a large master that no longer fights back.

### Added
- Mosaic stacking. Point Nocturne at a folder of subs covering several pointings, tick Mosaic in the Stack dialog, and it works out which frames belong to which panel from where the telescope was aimed, stacks each panel with the ordinary stacker, plate-solves them, builds one global frame on the sky and assembles a single wide picture — panel edges feathered, every overlap matched at once rather than pair by pair. It needs ASTAP installed and takes considerably longer than an ordinary stack. Built and validated on a 302-sub Andromeda mosaic.
- See what background extraction removed. After the step runs, tick Show what was removed to put the subtracted gradient on the canvas on its own. Mid-grey is where nothing was taken. A smooth ramp, brighter toward one edge or corner, is sky-glow and means the step did its job; if instead you can see the shape of your object in it, the model mistook your signal for sky and subtracted some of it — undo and try Light. That failure is nearly invisible in the corrected image, where the object merely looks a little flat, and obvious here.
- The stacking report now tells you the peak level a master was normalised by.

### Changed
- Large images are around five times quicker to work with. On a 39.5 megapixel mosaic, one move of a slider went from 2.66 seconds to 0.54, and opening that master from 12.4 seconds to 5.6. Nearly two thirds of the stretch was being spent computing four numbers — the median and spread of each channel — by reading every one of 39 million pixels twice. Reading a fixed, evenly spaced sample instead returns the same four numbers to within a ten-millionth. The sample is derived from the image's shape rather than chosen at random, so the same image always produces the same result and two exports can never differ. A test forces the exhaustive path back on and checks that not one pixel moves by more than one step in 256; on the real master the worst case was a quarter of a step.

### Fixed
- A mosaic master now records what went into it. It was written with its position on the sky in place of the usual stack details, so the frame count, exposure and filter were missing from the finished file.
- Show what was removed could not be clicked. Whether the control was available was worked out only when the step's panel was first drawn, and applying a step redraws the panel without rebuilding it — so after running background extraction the control stayed greyed out until you navigated to another step and back.
- The removed gradient was shown in the wrong colours. Background extraction takes out a fixed amount per colour channel as well as a gradient, and scaling all three channels together turned that fixed amount into colour: on a North America Nebula frame the gradient rendered vivid blue-green when it was in fact strongest in red. Each channel is now levelled on its own before the view is brightened, so colour in it once again means one channel genuinely had a stronger gradient than the others.
- A real gradient could be reported as nothing. The threshold below which the app decides nothing measurable was removed sat just above a gradient measured on a real 54-minute capture, so a slightly flatter sky would have answered “removed nothing measurable” for a correction that plainly changed the picture.

## [0.12.0] — 2026-08-15

Colours that match your data — and dialogs that open where you can see them.

### Changed
- Green removal now starts at zero. With the stretch fixed, most images have no green to remove — and on a clean image the old default of 0.40 was making the sky slightly greener, because green removal only acts where green exceeds red and blue, which on clean data happens only in the noise. It is still there, at whatever strength you choose, for an image that genuinely needs it.
- Projects saved before this release will reopen with the corrected colour, not the colour you saved. A saved project replays its steps rather than storing the finished pixels, so it now benefits from the fix.

### Fixed
- Images no longer come out green. The stretch — the step that lifts faint signal into view — was giving each colour channel its own amount of amplification, based on how noisy that channel was. A colour camera has twice as many green photosites as red or blue, so green arrives smoother, and the stretch mistook "smoother" for "needs more boost", amplifying green about twice as hard as the other channels. On a real Andromeda mosaic this turned a picture whose data was genuinely red-dominant into one that looked distinctly green. Photometric colour calibration reported no problem, correctly — the green was never in your data; it was added afterwards. The stretch now levels the channels first and brightens them all identically, so it changes brightness and never colour. Checked against five captures across a dark site and a light-polluted one, on both filters.
- The app no longer freezes when a dialog opens. On a second monitor, macOS was placing Open and Save panels on your primary display — and if Nocturne was fullscreen, on a different desktop entirely. The panel had control, so every click elsewhere just beeped and the app looked hung, with no way out but force-quitting and losing the session. File dialogs are now attached to Nocturne's own window, where they cannot wander off to another screen.
- Annotations no longer switch themselves back on. Hiding the plate-solve overlay and then zooming brought it straight back, because zooming rebuilds the overlay and your choice to hide it was stored on the thing being rebuilt.

## [0.11.2] — 2026-08-05

A fresh install no longer asks for Xcode before it will open a photograph.

### Fixed
- On a Mac without Apple's command line developer tools, launching Nocturne popped a system dialog asking to install them. Nothing was broken — dismissing it left the app working normally — but it is a poor thing to meet on a machine you have just installed on, and nothing about opening a FITS needs a compiler. The cause was a library Nocturne uses to debayer raw frames, which runs `git describe` when it loads in order to decorate a version string. On a developer's machine that fails quietly and is never noticed; without the tools installed, macOS answers the same call by offering to install them. Nocturne now stops that lookup before it can start a process, which the library already copes with by falling back to its packaged version number.

## [0.11.1] — 2026-08-05

Background extraction that does what the label says.

### Changed
- The Background strength control now has a real range. Both settings previously removed within about a percentage point of each other — measured across GraXpert's entire smoothing range, the choice spanned 2.2 points, which is not a choice. Light now removes roughly half of what Strong does, and Strong removes essentially the whole modelled gradient. That makes Light genuinely useful for the case it exists for: when your target fills the frame — a large galaxy, or a nebula spanning most of the picture — the model can mistake the object's faint outer parts for sky and subtract the very thing you came for. If Strong leaves your object looking flat or hollowed out at the edges, that is what happened; undo and try Light.

### Fixed
- Background extraction's two strengths were the wrong way round. The options are labelled by how much correction they apply, but were implemented as GraXpert's smoothing setting — the opposite axis, where a higher number means a stiffer model that removes LESS. So "strong" was gentler than "light", and the in-app help told you to reach for it when the gradient was heavy. Both now do what they say, and Strong is the default.

## [0.11.0] — 2026-08-04

Stacking that keeps your pixels — and a camera it recognises.

### Added
- Sharpen Nebulosity, an eleventh Enhancements tap. Sharpening a whole astro frame finds the noise first and rings the stars; this sharpens the starless layer under a signal mask and screens the stars back untouched, so nebula structure crisps up while stars cannot ring and the background is left alone. It is the easiest finishing move to overdo — one or two taps is usually right.
- Nocturne now recognises which Seestar took the picture, reading it from the file rather than assuming. Every camera question previously answered "S30 Pro", which is invisible if that is what you own and wrong otherwise — an S50's image scale is 2.39 arcsec/pixel against the S30 Pro's 3.74, enough to make a plate solve fail and quietly cost photometric colour its calibration. Adding a future model is a single entry.
- Trailed frames are now rejected when stacking. Wind, a nudge of the tripod or a tracking slip stretches the stars into short streaks, and that could not be detected before: frame sharpness is measured as the geometric mean of the two star axes, which is unchanged when a star is stretched one way and squeezed the other. A real frame with stars 70% longer than wide passed as a good one. A new Round column shows the measurement, where 1.00 is circular.
- Keep the full frame when stacking. An alt-az mount rotates the field as it tracks, so the outer edges of a stack are built from fewer frames than the middle, and Nocturne used to always trim back to the fully covered region — about a quarter of the picture. Turn "Trim the ragged edges" off and you keep everything. You can always crop later with the Crop step or Trim, but nothing can put back what the stacker discarded.
- Stacking says how far along it is. The progress bar fills once per phase, and reaching 100% only to restart with no explanation reads as a hang, so each phase now says "Step 2 of 3". Grading also explains itself while it runs, including that your Strictness and Integration choices apply instantly afterwards and never re-read the files.

### Changed
- Every frame is brought to a common sky level before combining. Sky brightness varies enormously across a session — 262% on a real M31 run, as the target climbed and the moon moved — so which frames a given pixel happened to average used to change its background. That drew the rotation pattern onto the finished picture as curved bands wherever the edges were kept.
- The in-app help now explains Strictness and Integration properly: what grading measures, what each option means in plain terms, when you would pick one over another, and why a frame count that does not change when you change Strictness is informative rather than broken. Sigma-clipping versus Average, and what the kappa setting actually does, are covered too.

### Fixed
- The edges of a stack came out dark. Frames that did not reach a pixel still counted toward its average, so an edge pixel covered by 10 of 80 frames came out at 12% of its true brightness — a smooth ramp inward that no amount of cropping could remove. Sigma-clipping appeared immune to this and was not.
- Frame grading could reject most of a good session. At Strict the quality threshold could fall below the session's own median, condemning perfectly typical frames; on a real session it rejected 37 of 60. The bright-sky warning had been misfiring the same way all along.
- Reset did nothing on a loaded project. It restored from a value that was only set when opening a FITS file, so it failed on every saved project — and reported the failure only to the console, leaving the button looking dead.
- A stacked master lost its optical details, so anything afterwards that needed the image scale fell back to an assumption instead of the real values. Masters now also record which camera took the data.

## [0.10.0] — 2026-08-02

Trim without losing your edit, a distraction-free view, and labels that stop colliding.

### Added
- Trim — cut the edges off a finished image without losing the edit. Ragged stacking borders and smeared corners are often invisible in the linear data you cropped at the start and only appear once you have stretched, at which point going back to the Crop step would discard every step you had done since. Trim adds a final step instead of reaching back, so the whole edit survives and undo still works. Available once the image is stretched.
- Press F for the image and nothing else — toolbar, step list, panels and the log all step aside so you can judge noise, star shapes and faint detail without the interface competing for attention. Escape returns, and your zoom and position are kept.
- Names for objects that had none. The deep-sky catalogues added recently arrived as bare designations, so the Elephant's Trunk appeared as "vdB 142". Eighteen of the best-known now carry the names people actually use — which also means a frame is more often identified as the thing you pointed at rather than as the largest catalogued region that happens to overlap it.

### Changed
- The in-app help now covers Trim, the full-screen view, the objects-in-field list, the Density control, Re-solve, the clipping line's "on import" reading, and Share's caption and output controls. It also says plainly that plate solving needs ASTAP's star database — a separate download from ASTAP itself, and much the most common reason a solve fails.

### Fixed
- Annotation labels could print on top of one another on a crowded field, rendering "LDN 1109" and "LDN 1110" as a single unreadable smear. Labels stay a fixed size on screen while their spacing was being worked out in image pixels, so at anything below 100% zoom they were larger than the space reserved for them. They now re-place themselves as you zoom. Burned exports were never affected.

## [0.9.0] — 2026-08-01

Plate solving that works beyond the Seestar — and several things that were quietly wrong.

### Added
- Plate solving no longer gives up when its assumed image scale turns out to be wrong. When a file carries no optical details in its header — which most stacked masters do not — Nocturne assumes the Seestar's image scale, which is right for a Seestar and badly wrong for anything else. If a solve fails with that assumption, it now drops the hint and tries again without one, so frames from other instruments can solve where they previously failed. The result card says when that happened, which is also the clearest available signal that a frame did not come from a Seestar.

### Fixed
- The same object could be named three different ways in the same window. The overlay labelled the Andromeda Galaxy "M 31" while the object list beside it and the solved-target line both called it "NGC 224". Every surface now uses the name people actually use.
- Dialogs that show an image — Share, Upscale Crop, Star Spikes — opened with the picture shrunk into the middle of the window, and only corrected themselves once you changed something. The view now re-fits when the window is resized, while leaving a zoom you chose deliberately alone.
- Sharing an annotated image drew the caption band on top of the annotations, swallowing the coordinate-grid labels and cutting object labels in half. With annotations burned in, the caption now sits below the picture by default, where it cannot cover anything — and you can still move it back onto the image if you prefer.

## [0.8.0] — 2026-08-01

Share grows up — and a colour fix that was quietly costing you accuracy.

### Added
- The Share caption is yours. Nocturne still writes a first draft from the image's own data — target, integration, frame count — but it is now an ordinary text field you can rewrite, trim, or replace with something the metadata never knew. Put it on the image or below it (below extends the canvas, so nothing you photographed is covered), left, centred or right, at three sizes, in any colour, with a slider for how dark the band behind it is. The styling is remembered between shares; the text starts fresh for each image.
- Share now lets you choose the output: 1080, 2048 or 4096 px, or full size, as JPEG or PNG. PNG is the better choice when the image carries annotations or a caption, since labels and text are hard edges and JPEG softens exactly those. Exports only ever scale down, and the status line reports the pixel size actually produced.
- The objects the plate solve found now appear beside the image by themselves, and follow the Annotations button rather than needing a separate control. Click a row to jump the view to that object; close it with its own ✕ if you would rather see the whole picture.
- Plate Solve is greyed out until ASTAP is configured, and says what to install rather than waiting for you to press it and then complaining.

### Changed
- The clipping warning now judges what your editing session actually caused, while still reporting the true total. An image that arrives already crushed — a re-imported export, or an upscaled copy — used to show amber from the first Stretch with nothing you could do about it, which is precisely the cry-wolf failure the warning was built to avoid. It now reads, for example, "0.9% shadows clipped (0.9% shadows on import)" and stays calm until you add to it.
- Share's aspect buttons show which one is selected. Previously nothing indicated the current choice, so the only way to know what you would get was to read the shape of the preview.
- Cropping, rotating or flipping a solved image now tells you the plate solve no longer lines up and its annotations have been hidden, instead of removing them in silence.

### Fixed
- Photometric colour (SPCC) silently fell back to sky balance on any master whose header carried no optical details — which is most stacked masters exported from another tool. The plate-solve tool already handled this by falling back to the Seestar's known image scale, but the colour step did not, so it solved blind, failed, and quietly used the lesser method. On a test capture this took it from no solution at all to 1,718 matched stars.
- A shared image ignored the plate-solved target. If your file's header never named what you photographed but Nocturne identified it, the caption left the target out entirely — while the info strip and the provenance report both showed it.
- Opening a new image left the previous image's annotation pill and object list on screen, describing a field you were no longer looking at.
- The plate-solve screenshot on this site and in the project README dated from before the annotation-mirroring fix, so both were illustrating the bug rather than the feature. Replaced with a current capture.

## [0.7.1] — 2026-08-01

Two correctness fixes — a bad pixel no longer blanks a channel, and a background step can't land on the wrong image.

### Fixed
- A single bad pixel could turn a whole colour channel black on screen. Frames registered with rotation (alt-az field rotation) often carry NaN "no data" in the corners, and one such pixel was enough to blank an entire channel of the display. Three faults compounded: importing a file containing NaN skipped normalisation entirely, leaving values far outside the range every later step assumes; the display stretch derived its parameters from a statistic that one bad sample destroys; and export cast those pixels differently from the canvas, so a saved file could disagree with what you were shown. Non-finite pixels are now treated the same way everywhere — as no data, drawn black — and the good pixels around them are unaffected.
- Opening or closing an image while a step was still running could corrupt it or crash. Closing a project mid-step raised an error; opening a different image mid-step silently applied the previous image's result to the new one and recorded it in the wrong history. Saving while opening another image could also write the new project to the old file. A result now only ever lands on the image it was computed for, and Open Project no longer silently does nothing while a step is running.

## [0.7.0] — 2026-07-31

Plate solving you can steer — an object list, a Cancel button that works, and annotations on Share.

### Added
- Objects in field — everything the solve found, as a list beside the image: deep-sky objects in the overlay's own significance order, named stars below with their magnitude. Click a row to jump the view to it. The list shows the whole field, including objects Density leaves off the image, so the ones hardest to spot are the ones easiest to reach.
- Share can carry your annotations. A checkbox switches the preview between the clean and the annotated frame, so a labelled image gets the social reframing and caption band too — previously the only way to publish a labelled image was a PNG export, which skips both. The checkbox is hidden entirely when there is no solution.
- Plate solving falls back to the instrument profile for the field-of-view hint when a file carries no optics. A stacked master exported from another tool routinely has neither FOCALLEN nor XPIXSZ, which left ASTAP solving a few-degree field blind and usually failing. The result card says when the scale was assumed rather than read, since on data from another instrument that assumption is wrong.

### Fixed
- Cancel during a plate solve did nothing. The button set the flag and the interface reported "Cancelling…" while ASTAP carried on to completion. It now genuinely stops the solver, and a solve still grinding after three minutes gives up with a diagnostic rather than holding on indefinitely.
- A pointing hint taken from a bare RA header card was parsed as hours when it was in degrees, making the search centre meaningless. Latent — those files carry pointing elsewhere too, so the bad value was never actually passed — but a file without that fallback would have been handed nonsense.
- The changelog on this site listed releases by headline alone, so you could not tell which version you were running. Every entry now names its version, and the newest is marked Latest.

## [0.6.0] — 2026-07-31

Plate solving grows up — and a fix that has been mislabelling your images since 0.3.0.

### Added
- Object circles are drawn at each object's real size on the sky instead of a fixed dot, so a large nebula's ring shows how far it extends — past the frame edge if the object is bigger than your field. A dashed ring means the catalogue records no size.
- A Plate Solve tool panel with a checkbox per layer (objects, named stars, RA/Dec grid, compass, scale bar), a Density control for how crowded the labels get, and a result card showing the field centre, size, scale, orientation, solver and elapsed time.
- Colour by type: violet Messier objects, white dark nebulae, cyan planetary nebulae, orange galaxies, yellow named stars.
- An RA/Dec coordinate grid, drawn as true curved lines with edge labels.
- Far more to find in your frames. The deep-sky catalogue grew from 13,962 NGC/IC objects to 15,890 by adding Sharpless HII regions, Lynds and Barnard dark nebulae and van den Bergh reflection nebulae — so the dark lane inside the North America Nebula is now labelled LDN 935. Named stars grew from 371 to 2,831 by adding Bayer and Flamsteed designations.
- An Annotations button on the image toggles the overlay without closing the tool, so you can keep the labels up while you carry on editing.

### Changed
- The Plate Solve toolbar button now opens the tool rather than solving immediately — solving starts when you press Solve, so a several-second run never begins by surprise.
- Labels are placed to avoid overlapping each other, in order of significance, with a leader line when a label has to sit away from its object.
- Labels are larger and carry a proper dark halo, so they stay readable over bright nebulosity as well as dark sky.
- Annotations are clipped to the image, and a solution is cleared when you crop, rotate or flip, since it belongs to the framing it was made for.
- The result card reports no confidence score and no mirrored/not-mirrored flag. Neither can be established reliably from what the solver returns, and a wrong claim on the panel that exists to tell you the solve is trustworthy is worse than a missing one.

### Fixed
- Every annotation was mirrored vertically. Object labels, stars, the grid and the compass have all been placed on the wrong side of the image since plate solving shipped in 0.3.0 — most visible on named stars, where a label sat in empty sky while the star was elsewhere in the frame. Large nebula circles disguised it because they landed roughly over their nebula either way.
- Photometric colour (SPCC) matched Gaia stars against the same mirrored positions, so its matches were coincidental rather than real. It now matches around 1,500 stars on a typical frame.
- Annotated PNG exports silently dropped named stars — the exported image no longer matches what the overlay showed.
- Sharpless objects were labelled with designations that do not exist (Sh 2117 instead of Sh 2-117), and drew a second ring and label over objects already catalogued, including on the North America and Orion nebulae.
- The identified target could be a huge diffuse complex that merely overlaps the frame rather than the object you photographed.

## [0.5.0] — 2026-07-31

Know exactly what you're looking at — pixel readout, clipping warnings, and a precise cursor.

### Added
- Hover pixel readout — a floating pill reports the pixel under your cursor: R/G/B (or V for mono) plus L luminance. Before Stretch it shows four decimals and tags the reading "linear", because the preview is auto-stretched while the value underneath is not.
- Clipping warning — from Stretch onward, a live summary under the histogram shows how much of the image is blown or crushed, naming the worst channel, and turns amber past a threshold calibrated on real Seestar stacks. Tick Show clipping to paint the affected pixels on the canvas (blue shadows, red highlights) live, even mid-slider-drag.
- Crosshair cursor over the image, so you can tell precisely which pixel a reading belongs to — the normal cursor everywhere else, and the grab hand while panning.
- Batch processing gained a Cancel button, and each failed file is now named with the reason it failed instead of a bare success count.

### Changed
- The Levels-only clipping checkbox is retired — clipping feedback is now global and works on every step from Stretch on, including Curves.
- Share and Upscale now ask you to Stretch first rather than silently producing a near-black result from linear data.
- Histogram redraws about 4x faster (126 ms to 36 ms on an 8 MP frame), so live previews are smoother.
- The in-app update link now uses HTTPS.

### Fixed
- Nocturne failed to start when run from a source checkout — a toolbar icon was missing from the repository, so launching from a fresh clone raised an error. The downloadable app was unaffected.
- Auto Enhance now gates on a crop and respects the crop you chose.
- Remove Green's live preview goes through the same canvas path as every other step, so what you see matches what applies.

## [0.4.2] — 2026-07-26

Five new one-tap Enhancements, plus recipe/batch capture and an in-app update check.

### Added
- Five new Enhancements taps — Star Colour (recover stars' natural colour via a star/starless split), Vibrance (oversaturation-resistant colour pop), Boost Gold (warm hue boost for dust and star fields), Dark Structure (definition in dust lanes and dark nebulae), and Soft Glow (dreamy Orton-style bloom).
- Enhancements taps are now captured in Recipes and replayed in Batch, so finishing survives folder processing.
- In-app "Update available" indicator — a fail-silent GitHub check on launch (no telemetry).

### Changed
- Refreshed in-app help, README, and testers' guide to cover the newer tools (Auto Enhance, Plate Solve, Share, Upscale Crop, Saved Projects, Provenance, Photometric/SPCC colour, ASTAP).

### Fixed
- The crop overlay now stays within the image — resizing or moving the box clamps to the bounds.

## [0.4.1] — 2026-07-25

Plate-solving fixed in the app build

### Fixed
- Plate Solve now works in the downloaded app — a packaging issue had it failing to solve or annotate (it had always worked when run from source).
- macOS "Get Info" now reports the correct app version.
- A plate-solve that can't complete now explains why, instead of showing a generic message.

## [0.4.0] — 2026-07-25

Saved projects, one-tap Auto Enhance, and shareable exports

### Added
- Saved Projects — save your whole editing session as a .nocturne file and reopen it exactly, pixel for pixel.
- Auto Enhance — one adaptive tap that detects dual-band vs broadband data and processes accordingly.
- Share — reframe and caption an image for social, then export or copy to the clipboard.
- Upscale Crop — a 2× layered upscale of any crop, exported or opened as a copy.
- Provenance report — a readable record of every step applied to an image, from the Project menu (Save or Copy).
- Cancel, live progress and failure diagnostics for long operations (stacking, grading, Auto Enhance, external tools).
- A histogram info strip (resolution · integration · target), Close Project, recent projects, and refreshed toolbar icons.

### Changed
- Auto Enhance reworked to always use photometric colour with a gentler stretch.
- The right panel no longer shifts as status messages update, and the message panels clear when a new image is opened.

### Fixed
- Readable FITS import details, a Close button on every dialog, and the Star Spikes preview now opens fitted to the image.

## [0.3.0] — 2026-07-23

The big feature build-out since the initial public release.

### Added
- **Plate Solve & Annotate** — solve any frame with ASTAP to identify the target and overlay deep-sky object labels, named stars, a compass and a scale bar. Annotations burn into PNG exports and the WCS is written into exported FITS.
- **Photometric colour calibration (SPCC)** — Gaia-based white balance in the Colour step, with an automatic fall-back to sky balance.
- **Guided Narrowband tool** — map Ha/OIII into finished palettes with a live preview, on the stars-removed image or the whole frame.
- **Curves** (a smooth monotone-cubic editor) and **HDR core recovery** for bright galaxy and nebula cores.
- **Star Spikes** — artistic diffraction spikes.
- **Denoise engine choice** — RC-Astro NoiseXTerminator, GraXpert, or a built-in method.
- **Frame grading in stacking** — a per-sub verdict, a strictness control, quality-ranked integration and a plain-language summary of what was kept.
- Free star separation, so Star Reduction, Remove Green Fringe and the nebula saturation boost work without RC-Astro.
- Remove Green Fringe, a masked nebula saturation boost, a default working folder, and spacebar before/after peek.

### Changed
- **Interface overhaul** — feedback is split into a timestamped log, a copyable output area, and a prominent warning area beside the buttons; Back/Next are pinned so they never shift; the detailed step-help is now a collapsible panel that remembers your choice; successes are no longer shown in alarm red.
- Every pipeline step audited and refined for beginners: accurate import integration time, a reworked Crop, per-channel Stretch, and live-preview Levels / Saturation / Local Contrast / Star Reduction.
- Robust background-neutralization replaces grey-world white balance in the Colour step (preserves real nebula colour).

### Fixed
- Numerous correctness and stability fixes across import, stacking, colour and the star-split pipeline.

## [0.2.0]

Prior baseline: the guided, non-destructive pipeline (live preview + full undo), built-in stacking, one-press Colourise, Ha/OIII extraction, real narrowband palettes, recipes & batch, and the native macOS app.
