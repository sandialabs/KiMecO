import logging
logging.basicConfig(
    filename='game.log',
    filemode='w',
    encoding='utf-8',
    datefmt='%m/%d/%Y %H:%M:%S ')
glog = logging.getLogger('rockme')
# create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

# create formatter
formatter = logging.Formatter('%(asctime)s | %(message)s')

# add formatter to ch
ch.setFormatter(formatter)

# add ch to logger
glog.addHandler(ch)

