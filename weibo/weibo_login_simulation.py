# !/usr/bin/python
# -*- coding=utf-8 -*-
import logging
import socket
import urllib.parse
from multiprocessing.pool import Pool
import pandas as pd
import re
import requests
from lxml import etree
from redis import StrictRedis
import time
import os
import json
import login_simulation

"""
    # 使用说明：基于python3.5
    # 执行参数分别为登陆帐号，登陆密码，是否用游览器引擎获取cookie（是的时候确保电脑有游览器引擎,并配置好相关信息）
    # 否的时候请自行登陆微博，手动获取cookie并存入文件.
    # 在解析html的时候，获取订阅者和粉丝是用lxml解析的，获取微博文本是用beautifulsoup解析的.
    !!!由于微博的限制，现在爬虫只能爬前5页的粉丝列表以及订阅列表，除非用其它方法!!!
"""


# TODO(ximingren): 解决只能访问粉丝和订阅者列表前5页的问题
# TODO(ximingren): 点赞的微博不要
# TODO(ximingren): list index out of range;'NoneType' object is not callable
# TODO(ximingren): 添加日志功能  OK!!
# TODO(ximingren): 存储到数据库中 (目前只使用了redis数据库存储)
# TODO(ximingren): 构建IP代理池 （暂时只是用了他人代建的代理池实现了代理爬取）
# TODO(ximingren): 优化变量命名
# TODO(ximingren): 模拟登陆而不用selenium获取cookie OK!!
# TODO(ximingren): 实现模拟登录  OK!!
# TODO(ximingren): 'NoneType' object has no attribute 'xpath'
# TODO(ximingren): line 1: b'Attribute rnt redefined' (line 1)
# TODO(ximingren): line 2450: b"htmlParseEntityRef: expecting ';'" (line 2450)

def log_setting():
    """
    日志记录功能
    :return: 
    """
    global logger
    logger = logging.getLogger('weibo_logger')
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler('weibo_logger.log')
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(module)s.%(funcName)s.%(lineno)d - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(ch)

# def insert_data(db,table,data):
#     cursor=db.cursor()
#     keys=','.join(data.keys())
#     values=','.join(['%s']*len(data))
#     sql='INSERT INTO {table}({keys}) VALUES ({values})'.format(table=table,keys=keys,values=values)
#     try:
#         if cursor.execute(sql,tuple(data.values())):
#             print('Successful')
#             db.commit()
#     except:
#         print('Failed')
#         db.rollback()

def openlink(url, session):
    """
    urlopen error 10060错误
    :param url:  请求的网址
    :param headers: 报文头部信息
    :return: 服务器响应
    """
    global proxies
    maxTryNum = 15
    for tries in range(maxTryNum):
        try:
            if use_proxy:
                response=session.get(url,proxies=proxies)
            else:
                response = session.get(url)
            return response
        except:
            if tries < (maxTryNum - 1):
                proxies=get_ip_list(ips_url)
                continue
            else:
                logger.info("尝试%d 次连接网址%s失败!" % (maxTryNum, url))


def get_timestamp():
    """
    获取当前系统时间戳
    :return:  系统时间戳
    """
    try:
        tamp = time.time()
        timestamp = str(int(tamp)) + "000"
        return timestamp
    except Exception as e:
        logger.error(e)

    finally:
        pass


def mkdir(path):
    """
    创建新目录(如果不存在)
    :param path:
    :return:
    """
    try:
        folder = os.path.exists(path)
        if not folder:
            os.makedirs(path)
    except Exception as e:
        logger.error(e)

    finally:
        pass


def login_weibo_get_cookies(driver):
    """
    登陆获取cookie,然后进行处理
    :param driver: chromedriver
    :return: 处理后的cookie
    """
    try:
        time.sleep(2)
        driver.find_element_by_name("username").send_keys(username)  ##输入用户名
        driver.find_element_by_name("password").send_keys(password)  ##输入密码
        driver.find_element_by_xpath("//a[@node-type='submitBtn']").click()  ##点击登录按钮
        cookies = driver.get_cookies()  ##获取cookies
        cookie = ""
        # 将返回的Cookies数组转成微博需要的cookie格式
        for x in range(len(cookies)):
            value = cookies[x]['name'] + "=" + cookies[x]['value'] + ";"
            cookie = cookie + value
        return cookie
    except Exception as e:
        logger.error(e)


def analyse_html(tree, name):
    """
    HTML代码藏在script中，解析出HTML代码
    :param soup: BeautifulSoup对象
    :param name: 所需的html所在的script的name
    :return: 包含结果html的beautifulsoup
    """
    try:
        script_list = tree.xpath("//script//text()")  # 要抓取的内容在scirpt里面,首先先解析出script
        script_size = len(script_list)
        tag = 0
        for x in range(script_size):
            if name in str(script_list[x]):
                tag = x
        html_start = str(script_list[tag]).find("<div")  # 找到最前面的div标签
        html_end = str(script_list[tag]).rfind("div>")  # 找到最后面的div标签
        parser_html = str(str(script_list[tag])[html_start:html_end + 4])  # 找出需要的html文本
        result_html = parser_html.replace("\r\n", "")  # 处理成合适的规格
        result_html = result_html.replace("\\", "")  # 处理成合适的规格
        result_etree = etree.HTML(result_html)  # 对处理后的html进二次解析
        return result_etree
    except Exception as e:
        logger.error(e)


def get_info(name, session):
    """
    获取用户的订阅者数、粉丝数、微博数
    :param name: 用户昵称
    :param headers: 报文头部信息
    :return: condition: 若用户存在,condition为list[subs_page,fans_page,id]
    :return: condition: 若用户不存在,condition为空list
    """
    try:
        search_url = "https://m.weibo.cn/api/container/getIndex?containerid=100103type%3D3%26q%3D"
        info_response = openlink(search_url + name + "&page_type=searchall",session)  # 微博搜索的页面url
        data = json.loads(info_response.text)
        condition = []
        if data['data']['cards']:
            search_size = len(data['data']['cards'][1]['card_group'])
            for k in range(search_size):
                if data['data']['cards'] and data['data']['cards'][1]['card_group'][k]['user']['screen_name'] == name:
                    profile_url = data['data']['cards'][1]['card_group'][k]['user']['profile_url']
                    id = int(re.findall(r"/u/(\d.+)\?", profile_url)[0])
                    subs_size = data['data']['cards'][1]['card_group'][k]['user']['follow_count']
                    fans_size = data['data']['cards'][1]['card_group'][k]['user']['followers_count']
                    logger.info("%s的订阅者数：%d   粉丝数%d" % (name, subs_size, fans_size))
                    if fans_size > 20:
                        fans_page = int(round(fans_size / 20))  # 计算出粉丝列表的具体页数
                    elif fans_size != 0:
                        fans_page = 1
                    else:
                        fans_page = 0
                    if subs_size > 20:
                        subs_page = int(round(subs_size / 20))  # 计算出订阅列表的具体页数
                    elif subs_size != 0:
                        subs_page = 1
                    else:
                        subs_page = 0
                    condition = [subs_page, fans_page, id]
                    redis.hset(name,'subs_page',str(subs_page)) # 存入redis中，
                    redis.hset(name,'fans_page',str(fans_page)) # 存入redis中，
                    # insert_data(mysql_db,mysql_table,{'id':id,
                    #                                   'subs_page':str(subs_page),
                    #                                   'fans_page':str(fans_page)})
        if not condition:
            logger.info("将失效昵称写入文件中,失效昵称:%s" % name)
            with open('failure.txt', 'a') as f:
                f.write(name + "\n")
        return condition
    except Exception as e:
        logger.error(e)
        logger.info("发生异常", e)
    finally:
        pass


def get_top_contents(weibo_id, name, session, page):
    """
    获取顶部微博文本
    :param weibo_id: 用户ID
    :param name: 用户昵称
    :param headers: 头部信息
    :param page: 页码
    :return:
    """
    try:
        cont_url = "https://weibo.com/p/100505" + weibo_id + "?is_search=0&visible=0&is_all=1&is_tag=0&profile_ftype=1&page=" + str(
            page)  # 拼凑成订阅者列表的页面url
        weibo_div_size = 0
        count = 0
        # 因为有时会出现连接失败，返回的页面是空的，所以反复请求连接直到有页面为止
        while (weibo_div_size == 0):
            count = count + 1
            logger.info("使用代理%s请求连接到微博内容页面:%s" % (proxies,cont_url))
            response = openlink(cont_url, session)
            html = response.content.decode()  # 对调用接口后传过来的内容进行解码
            logger.info("解析微博文本内容%d次" % count)
            cont_etree = etree.HTML(html)
            cont_etree = analyse_html(cont_etree, "pl.content.homeFeed.index")
            weibo_div = cont_etree.xpath('//div[@class="WB_detail"]')  # 找到所有的div内容框，返回的是结果集
            weibo_div_size = len(weibo_div)
            for k in weibo_div:
                text = k.xpath('./div[@class="WB_text W_f14"]/text()')[0]
                weibo_time = k.xpath('.//a[@class="S_txt2" and @target="_blank"]/@title')[0]
                phone = k.xpath('.//a[@class="S_txt2" and @target="_blank"]/text()')[1]
                redis.hset(name,"content_"+str(page)+"_top",str([weibo_time,phone,text.strip('n')]))
                # insert_data(mysql_db,mysql_table,{'id':weibo_id,
                #                                   "contents"+str(page)+"_top":str([weibo_time,phone,text.strip('n')])})
            if count >= 3 and count <= 5:
                logger.info("连续解%d次失败，休眠10秒后再爬" % count)
                time.sleep(10)
            # 这个是为了请求6页以后，微博限制用户访问列表，不再继续爬
            if count > 5:
                logger.info("解析%s页面第%d页微博文本页面失败!!!!" % (name, page))
                break
        logger.info("休眠两秒后继续爬")
        time.sleep(2)
    except Exception as e:
        logger.error(e)
        logger.info("发生异常", e)
    finally:
        pass


def get_contents(weibo_id, name, session, pagebar, page, content_page):
    """
    通过微博ID和cookie来调取接口
    :param weibo_id: 用户ID
    :param name: 用户昵称
    :param session: 头部信息
    :param pagebar:滑动页码
    :param page:页码
    :param content_page:总微博页码
    :return:
    """
    try:
        # headers['Referer'] = "https://weibo.com/p/100505" + weibo_id
        weibo_div_size = 0
        count = 0
        # 因为有时会出现连接失败，返回的页面是空的，所以反复请求连接直到有页面为止
        while (weibo_div_size == 0):
            global page_div
            count = count + 1
            params = urllib.parse.urlencode(
                {'ajwvr': 6, 'domain': 100505, "profile_ftype": 1, 'is_all': 1, 'pagebar': pagebar,
                 "pl_name": "Pl_Official_MyProfileFeed__22", "id": "100505" + weibo_id,
                 "script_uri": "/p/" + "100505" + weibo_id,
                 'feed_type': 0, 'page': page + 1, 'pre_page': page + 1, 'domain_op': 100505,
                 '__rnd': get_timestamp()})  # 调用接口时所用的参数
            cont_url = api_url + "%s" % (params)
            logger.info("使用代理%s请求连接到微博内容页面:%s" % (proxies,cont_url))
            response = openlink(cont_url, session)
            html = response.content.decode()  # 对调用接口后传过来的内容进行解码
            cont_html = json.loads(html)['data']
            logger.info("解析微博文本内容%d次" % count)
            cont_etree = etree.HTML(cont_html)
            # 如钩没加载完则返回True,继续加载。如果加载完了返回False，不用接着加载了
            weibo_div = cont_etree.xpath('//div[@class="WB_detail"]')  # 找到所有的div内容框，返回的是结果集
            weibo_div_size = len(weibo_div)
            empty_flat = cont_etree.xpath('//div[@class="WB_empty WB_empty_narrow"]')  # 加载完没内容了，会出现页码
            page_div = cont_etree.xpath('//div[@class="W_pages"]')
            # 同时出现empty标签和微博内容div为空,或者出现页码条和没到最后一次滑动
            if (empty_flat and not weibo_div) or (page_div and (pagebar + 1) != 2):
                logger.info("第%d页第%d次滑动没有内容" % (page + 1, pagebar + 1))
                break
            for k in weibo_div:
                text = k.xpath('./div[@class="WB_text W_f14"]/text()')[0]
                weibo_time = k.xpath('.//a[@class="S_txt2" and @target="_blank"]/@title')[0]
                phone = k.xpath('.//a[@class="S_txt2" and @target="_blank"]/text()')[1]
                redis.hset(name, "content_" + str(page) +"_pagebar_"+str(pagebar), str([weibo_time, phone, text.strip('n')]))
                # insert_data(mysql_db, mysql_table, {'id': weibo_id,
                #                                     "content_" + str(page)+"_pagebar_"+str(pagebar): str(
                #                                         [weibo_time, phone, text.strip('n')])})
            if page + 1 != content_page and count >= 3 and count <= 5:
                logger.info("连续解析%d次失败，休眠15秒后再爬" % count)
                time.sleep(15)
            if page + 1 != content_page and count > 5:
                logger.info("解析%s页面第%d页微博列表面失败!!!!" % (name, page + 1))
                break
            if page + 1 == content_page and count >= 3 and count <= 5:
                logger.info("连续解析最后一个页面%d次失败，休眠15秒后再爬" % count)
                time.sleep(15)
            if page + 1 == content_page and count > 5:
                logger.info("解析解析%s页面第最后一页微博列表面失败！！！" % (name))
                logger.info("这是最后一页")
                break

    except Exception as e:
        logger.error(e)

    finally:
        pass


def get_subs(weibo_id, name, session, subs_list_page):
    """
    获取订阅者的信息并写入文件
    :param weibo_id: 微薄ID
    :param name: 微薄昵称
    :param session: 头部信息
    :param subs_list_page: 订阅者列表总页码
    :return:
    """
    try:
        redis_subs_list=list()
        if subs_list_page > 5:
            subs_list_page = 5
        for page in range(0, subs_list_page):
            subs_url = "https://weibo.com/p/100505" + weibo_id + "/follow?page=" + str(
                page + 1) + "#Pl_Official_HisRelation__59"  # 拼凑成订阅者列表的页面url
            logger.info("使用代理%s爬取%s的订阅者列表的网址:  %s\n" % (proxies,name, subs_url))
            logger.info("请求连接到%s的订阅者列表页面" % name)
            logger.info("正在爬取%s的订阅者第%d页" % (name, page + 1))
            subs_size = 0
            count = 0
            # 因为有时会出现连接失败，返回的页面是空的，所以反复请求连接直到有页面为止
            while (subs_size == 0):
                count = count + 1
                subs_response = openlink(subs_url, session)
                subs_html = subs_response.content.decode()
                logger.info("解析%s的订阅者html页面%d次" % (name, count))
                subs_etree = etree.HTML(subs_html)
                subs_etree = analyse_html(subs_etree, "pl.content.followTab.index")
                # 写入redis数据库中
                subs_list = subs_etree.xpath('//a[@class="S_txt1" and @target="_blank"]')
                subs_size = len(subs_list)
                for x in subs_list:
                    if x.text is not None:
                        redis_subs_list.append(str(x.text)+str(x.get('href')))# 订阅者的昵称,订阅者连接
                if count >= 3 and count <= 5:
                    logger.info("连续解%d次失败，休眠10秒后再爬" % count)
                    time.sleep(10)
                # 这个是为了请求6页以后，微博限制用户访问列表，不再继续爬
                if count > 5:
                    logger.info("解析%s页面第%d页订阅列表页面失败!!!!" % (name, page + 1))
                    break
            redis.hset(name,'subs_list',str(redis_subs_list))
            # insert_data(mysql_db,mysql_table,{'id':weibo_id,
            #                                   'subs_list':str(redis_subs_list)})
            logger.info("休眠两秒后继续爬下一页")
            time.sleep(2)
    except Exception as e:
        logger.error(e)
        logger.info("发生异常", e)
    finally:
        pass


def get_fans(weibo_id, name, session, fans_list_page):
    """
    获取粉丝信息并写入文件
    :param weibo_id: 微薄ID
    :param name: 微薄昵称
    :param session: 头部信息
    :param fans_list_page: 粉丝列表总页码
    :return:
    """
    try:
        redis_fans_list=list()
        if fans_list_page > 5:
            fans_list_page = 5
        for page in range(0, fans_list_page):
            fans_url = "https://weibo.com/p/100505" + weibo_id + "/follow?relate=fans&page=" + str(
                page + 1) + "#Pl_Official_HisRelation__59"  # 拼凑粉丝列表url
            logger.info("爬取%s的粉丝列表的网址：  %s\n" % (name, fans_url))
            logger.info("请求连接到%s的粉丝列表页面" % name)
            logger.info("正在爬取%s的粉丝列表第%d页" % (name, page + 1))
            fans_size = 0
            count = 0
            # 因为有时会出现连接失败，返回的页面是空的，所以反复请求连接直到有页面为止
            while (fans_size == 0):
                count = count + 1
                fans_response = openlink(fans_url, session)
                fans_html = fans_response.content.decode()
                logger.info("v解析%s的粉丝列表html页面%d次" % (name, count))
                fans_etree = etree.HTML(fans_html)
                fans_etree = analyse_html(fans_etree, "pl.content.followTab.index")  # 获取处理过的html
                fan_list = fans_etree.xpath('//a[@class="S_txt1"  and @target="_blank"]')
                fans_size = len(fan_list)
                for x in fan_list:
                    if x.text is not None:
                        redis_fans_list.append(str(x.text) + str(x.get('href')))  # 粉丝的昵称,粉丝连接
                if count >= 3 and count <= 5:
                    logger.info("连续解%d次失败，休眠10秒后再爬" % count)
                    time.sleep(10)
                # 这个是为了请求6页以后，微博限制用户访问列表，不再继续爬
                if count > 5:
                    logger.info("解析%s页面第%d页粉丝列页面失败!!!!" % (name, page + 1))
                    break
            redis.hset(name,'fans_list',str(redis_fans_list))
            # insert_data(mysql_db,mysql_table,{'id':weibo_id,
            #                                   'fans_list':str(redis_fans_list)})
            logger.info("休眠两秒后继续爬下一页")
            time.sleep(2)

    except Exception as e:
        logger.error(e)
        logger.info("发生异常", e)
    finally:
        pass


def get_contents_page(weibo_id, name, session, pagebar, page):
    """
    获取微博内容并写入文件
    :param weibo_id: 微薄ID
    :param name: 微薄昵称
    :param session: 头部信息
    :param pagebar: 滑动页面
    :param page: 页码
    :return:
    """
    try:
        url = "https://weibo.com/p/100505" + weibo_id + "/home?profile_ftype=1&is_all=1#_0"
        response = openlink(url, session)
        html = response.content.decode()
        cont_page_etree = analyse_html(etree.HTML(html), "Pl_Core_T8CustomTriColumn__3")
        info = cont_page_etree.xpath('//strong[@class="W_f18"]')
        weibo_size = info[2].text
        logger.info("%s共有%s条微博" % (name, weibo_size))
        if int(weibo_size) == 0:
            return 0
        if int(weibo_size) < 40:
            return 1
        else:
            weibo_div_size = 0
            count = 0
            # 因为有时会出现连接失败，返回的页面是空的，所以反复请求连接直到有页面为止
            while (weibo_div_size == 0):
                count = count + 1
                params = urllib.parse.urlencode(
                    {'ajwvr': 6, 'domain': 100505, "profile_ftype": 1, 'is_all': 1, 'pagebar': pagebar,
                     "pl_name": "Pl_Official_MyProfileFeed__22", "id": "100505" + weibo_id,
                     "script_uri": "/p/" + "100505" + weibo_id,
                     'feed_type': 0, 'page': page + 1, 'pre_page': page + 1, 'domain_op': 100505,
                     '__rnd': get_timestamp()})  # 调用接口时所用的参数
                cont_url = api_url + "%s" % (params)
                logger.info("使用代理%s请求连接到%s的微博内容页面:%s" % (proxies,name, cont_url))
                response = openlink(cont_url, session)
                html = response.content.decode()  # 对调用接口后传过来的内容进行解码
                cont_html = json.loads(html)['data']
                logger.info("解析%s的微博文本内容%d次" % (name, count))
                cont_etree = etree.HTML(cont_html)
                content_page = int(re.sub("\D", "", cont_etree.xpath('//a[@bpfilter="page"]/text()')[1]))
                return content_page
    except Exception as e:
        logger.error(e)
        logger.info("发生异常", e)


def crawl_main(name):
    """
    爬虫程序入口
    :param name:微薄昵称
    :return:
    """
    global proxies
    proxies = get_ip_list(ips_url)  # 获取代理
    logger.info("使用代理%s爬取%s的订阅者数,粉丝数以及微博数" % (proxies,name))
    info = get_info(name, weibo.session)  # 获取个人信息
    if info:
        weibo_id = str(info[2])  # 微博id
        logger.info("要爬取的账号的ID：" + weibo_id)
        logger.info("爬取订阅列表,共有%d页" % (info[0]))
        get_subs(weibo_id, name, weibo.session, info[0])
        logger.info("10秒后爬取粉丝列表")
        time.sleep(10)
        logger.info("爬取粉丝列表,共有%d页" % (info[1]))
        get_fans(weibo_id, name, weibo.session, info[1])
        logger.info("10秒后爬取文本列表")
        time.sleep(10)
        content_page = get_contents_page(weibo_id, name, weibo.session, 1, 1)
        redis.hset(name,'content_page',content_page) #向redis插入数据
        # insert_data(mysql_db,mysql_table,{'content_page':content_page}) # 向mysql插入数据
        logger.info("爬取微博文本,共有%d页" % (content_page))
        for page in range(content_page):  # info[2]是微博列表的总页码
            logger.info("正在爬取第%d页顶部内容" % (page + 1))
            get_top_contents(weibo_id, name, weibo.session, page + 1)  # 先加载出顶部微博内容
            time.sleep(3)
            for slide in range(0, 2):  # 两次下滑加载内容
                logger.info("正在爬取第%d页内容第%d次滑动加载更多" % (page + 1, slide + 1))
                get_contents(weibo_id, name, weibo.session, slide, page, content_page)
                logger.info("休眠3秒后继续爬下一次滑动")
                time.sleep(3)
            logger.info("休眠3秒后继续爬下一页")
            time.sleep(3)
        logger.info("30秒后爬取下一个用户的信息")
        time.sleep(30)
    # mysql_db.close()


def get_ip_list(url):
    web_data = json.loads(requests.get(url).content.decode('utf-8'))
    logging.info("进程%d获取代理IP地址"%os.getpid())
    ip_condition=True
    proxies=dict()
    try:
        while ip_condition:
            if web_data['msg'] == 'success':
                url=web_data['data']['detail'][0]['url']
                proxies['http'] =url
                ip_condition=detect_list(proxies)
        return proxies
    except Exception as e:
        print("获取代理失败",e)

def detect_list(proxies):
    try:
        logging.info("进程%d对代理%s进行检测"%(os.getpid(),str(proxies)))
        r = requests.get("http://www.ip138.com/", proxies=proxies)
        if r.ok:
            logging.info("进程%d代理%s检测成功"%(os.getpid(),str(proxies)))
            return False
        return True
    except Exception as e:
        logging.error("进程%d代理检测失败"%(os.getpid()),e)

# 主程序入口
if __name__ == "__main__":
    """下面是定义各种属性的地方，有一些需要根据自己实际情况来定"""
    weibo_url = "http://weibo.com/"  # 微博域名
    ips_url="http://localhost:12345/api/proxy/?count=1&scheme=HTTP&anonymity=anonymous"
    api_url = "http://weibo.com/p/aj/v6/mblog/mbloglist?"  # 微博文本抓取的apt
    excel_name = './weibo/19520816_0_个人性格调查问卷_101_101.xls'
    socket.setdefaulttimeout(25)  # 定义超时时间,25秒
    redis=StrictRedis(host='localhost',port=6379)
    # mysql_db=pymysql.connect(db="spiders")
    # mysql_table="weibo_sfc"
    log_setting()
    username = input('输入帐号')
    password = input('输入密码')
    logging.info('进行微博模拟登录')
    weibo = login_simulation.WeiBoLogin()  # 微博模拟登录实例
    weibo.login(username, password)  # 进行微博模拟登录
    logging.info('微博模拟登录成功')
    use_proxy = True # 使用代理模式
    data = pd.read_excel(excel_name)  # 读取excel表格
    names_list = data['微博昵称']  # 获取昵称的列值
    pool = Pool()
    pool.map(crawl_main, names_list)
