"""Browser helpers for the K1/K3 pickers of the Learning review pages (photo list, class chips)."""


def choose_pixel_frame(page, index):
    """Pick a photo in the K3 list (the folded photo tool); the open photo is the aria-selected option."""
    page.evaluate('(id)=>location.hash=id', 'pixel-photo-list')
    page.wait_for_function('()=>document.querySelector("#pixel-frames").getBoundingClientRect().height>0')
    page.locator(f'#pixel-frames [role=option][data-id="{index}"]').click()
    page.evaluate('(id)=>location.hash=id', 'pixel-review')  # back to the photo review tool, as the old always-visible select left it


def choose_pixel_class(page, value):
    """Choose a pixel class chip (K1 radio group); '' is the explicit 'no class' chip, 255 the erase chip."""
    page.locator(f'#pixel-class label:has(input[value="{value}"])').click()
