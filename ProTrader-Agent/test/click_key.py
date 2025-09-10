import time

from utils.mouse import move_click
from utils.keyboard import type_text

if __name__ == '__main__':
    move_click(2000, 1000)
    #type_text("Mettre une liste deroulante ou deroulante au lieu de bouton radio.")
    time.sleep(2)
    move_click(250, 750)
    time.sleep(2)