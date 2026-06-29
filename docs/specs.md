Application Flow:

User should be presented with one step at a time, not one massive view with all the options as that could be overwhelming

1. Load image:
    This opens up the fits file and performs an autostretch so the user can see the image, the actual editing will not happen on the autostretched image but rather the linear so autostretch is only there to enable the user to see the reults. 

2. Cropping. 
    LEts the user crop the image, this can be fixed ratios, 5, 10 or perhaps 15% from the edges
    User should be able to choose a centerpoint of the image
    User should be able to choose final aspect ratio for example 1:1, 16:9, 4:5 etc
    Flip and rotate image

3. Background extration (remove gradient)
    Either using Graxpert or RC-Astro tools


4. Background neutralization / Color correction

5. Deconvolution / Sharpening
    Either BlurXTerminator (RC Astro) or a general "High pass" filter sharpen (lucy richardsson)

6. Noise Reduction
    Graxpert / RC Astro with pre-defined values

7. Stretch
    This is a real stretch as everything afterwards should happen with stretched data. 


8. Final Fixes

Re-Calibrate color
Remove green cast
Masked saturation
Increase blues
Darker Sky
Lighter Sky

















    Assumptions:

    Preferably this application should be built using a modular approach so we can add features and functions as we go a head. i.e. build on it over time.
    We will assume that the user provides a stacked image to begin with.
    Undo / Redo functions for all changes to an image.
    For every action there should be a compate before/after button
    Graxpert is free and the application should require it.
    RC-Astro is not free and should be optional.
    User should be able to provide URLs for the RC astro and Graxpert files in a settings page.
    Application should be dedicated to ZWO seestar S30 Pro images
    User should be able to go back to previous steps if they did a mistake in an earlier step. 

    
