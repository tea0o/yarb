#!/usr/bin/python3

import os
import json
import time
import schedule
import pyfiglet
import argparse
import datetime
import listparser
import feedparser
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from bot import feishuBot
from utils import Color

import requests
requests.packages.urllib3.disable_warnings()


def update_rss(rss: dict):
    """更新订阅源文件"""
    (key, value), = rss.items()
    rss_path = root_path.joinpath(f'rss/{value["filename"]}')

    result = None
    url = value.get('url')
    if url:
        r = requests.get(value['url'])
        if r.status_code == 200:
            with open(rss_path, 'w+') as f:
                f.write(r.text)
            print(f'[+] 更新完成：{key}')
            result = {key: rss_path}
        else:
            if rss_path.exists():
                print(f'[-] 更新失败，使用旧文件：{key}')
                result = {key: rss_path}
            else:
                print(f'[-] 更新失败，跳过：{key}')
    else:
        print(f'[+] 本地文件：{key}')

    return result


def parseThread(url: str):
    """获取文章线程"""
    title = ''
    result = {}
    try:
        r = requests.get(url, timeout=10, verify=False)
        r = feedparser.parse(r.content)
        title = r.feed.title
        for entry in r.entries:
            d = entry.get('published_parsed')
            if not d:
                d = entry.updated_parsed
            yesterday = datetime.date.today() + datetime.timedelta(-1)
            pubday = datetime.date(d[0], d[1], d[2])
            if pubday == yesterday:
                item = {entry.title: entry.link}
                print(item)
                result.update(item)
        Color.print_success(f'[+] {title}\t{url}\t{len(result.values())}/{len(r.entries)}')
    except Exception as e:
        Color.print_failed(f'[-] failed: {url}')
        print(e)
    return title, result


def init_bot(conf: dict):
    """初始化机器人"""
    bots = []
    bot_conf = conf['feishu']
    if bot_conf['enabled']:
        key = os.getenv(bot_conf['secrets'])
        if not key:
            key = bot_conf['key']
        bots.append(feishuBot(key))
    return bots


def init_rss(conf: dict, update: bool=False):
    """初始化订阅源"""
    temp_list = [{k: v} for k, v in conf.items() if v['enabled']]
    rss_list = []
    if update:
        for rss in temp_list:
            rss = update_rss(rss)
            if rss:
                rss_list.append(rss)
    else:
        for rss in temp_list:
            (key, value), = rss.items()
            rss_list.append({key: root_path.joinpath(f'rss/{value.filename}')})

    # 合并相同链接
    feeds = []
    for rss in rss_list:
        (_, value), = rss.items()
        rss = listparser.parse(open(value).read())
        for feed in rss.feeds:
            url = feed.url.strip('/')
            if url not in feeds:
                feeds.append(url)

    Color.print_focus(f'[+] {len(feeds)} feeds')
    return feeds


def job(args):
    """定时任务"""
    print(pyfiglet.figlet_format('yarb'))
    print(datetime.datetime.now())

    global root_path
    root_path = Path(__file__).absolute().parent
    if args.config:
        config_path = Path(args.config).expanduser().absolute()
    else:
        config_path = root_path.joinpath('config.json')
    with open(config_path) as f:
        conf = json.load(f)
    bots = init_bot(conf['bot'])
    feeds = init_rss(conf['rss'], args.update)

    # 获取文章
    results = []
    numb = 0
    tasks = []
    with ThreadPoolExecutor(50) as executor:
        for url in feeds:
            tasks.append(executor.submit(parseThread, url))
        for task in as_completed(tasks):
            title, result = task.result()            
            if result:
                numb += len(result.values())
                results.append({title: result})
    Color.print_focus(f'[+] {len(results)} feeds, {numb} articles')

    # 推送文章
    for result in results:
        (key, value), = result.items()
        text = f'{key}\n\n'
        for k, v in value.items():
            text += f'{k}\n{v}\n\n'
        text = text.strip()
        print(text)

        for bot in bots:
            bot.send_text(text)


def argument():
    parser = argparse.ArgumentParser()
    parser.add_argument('--update', help='Update RSS config file', action='store_true', required=False)
    parser.add_argument('--cron', help='Execute scheduled tasks every day (eg:"11:00")', type=str, required=False)
    parser.add_argument('--config', help='Use specified config file', type=str, required=False)
    return parser.parse_args()


if __name__ == '__main__':
    args = argument()
    if args.cron:
        schedule.every().day.at(args.cron).do(job, args)
        while True:
            schedule.run_pending()
            time.sleep(1)
    else:
        job(args)
