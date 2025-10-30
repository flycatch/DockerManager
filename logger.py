import datetime

debug = True

def log(text):
    if debug:
        with open('log.txt', 'a') as f:
            f.write(f"{datetime.datetime.now()} {text}\n")