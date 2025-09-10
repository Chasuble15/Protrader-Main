import time

from utils.vision import find_template_on_screen

while True:
    time.sleep(1)
    result = find_template_on_screen(
        template_path="../assets/btn_jouer.png",
        debug=True,
    )
    print(result)