# -*- coding: utf-8 -*-
"""
    定义一些任务的执行操作，将具体的操作从tasks.py里面抽离出来
    每个任务需要饮用的模块放到函数里面引用，方便单独调试函数
"""
import json
from datetime import datetime, timedelta
from blog.utils import RedisKeys
import requests


def get_link_status(url):
    """
    请求地址，返回请求状态和内容
    @param url:
    @return:
    """
    try:
        resp = requests.get(url, timeout=5, verify=False)
    except Exception:
        return 500, '请求超时'
    return resp.status_code, resp.text


def white_list_check(lis, string):
    """
    校验一个字符串是否包含一个列表中任意一个元素
    @param lis:
    @param string:
    @return: bool
    """
    for each in lis:
        if each in string:
            return True
    return False


def action_update_article_cache():
    """
    更新所有文章的缓存，缓存格式跟文章视图保持一致
    @return:
    """
    from markdown import Markdown
    from markdown.extensions.toc import TocExtension  # 锚点的拓展
    from markdown.extensions.codehilite import CodeHiliteExtension
    from django.core.cache import cache
    from django.utils.text import slugify
    from blog.utils import CustomHtmlFormatter
    from blog.models import Article

    total_num, done_num = 0, 0
    # 查询到所有缓存的key
    keys = cache.keys('article:markdown:*')
    for obj in Article.objects.all():
        total_num += 1
        ud = obj.update_date.strftime("%Y%m%d%H%M%S")
        md_key = f'article:markdown:{obj.id}:{ud}'
        # 设置不存在的缓存
        if md_key not in keys:
            md = Markdown(extensions=[
                'markdown.extensions.extra',
                'markdown_checklist.extension',
                CodeHiliteExtension(pygments_formatter=CustomHtmlFormatter),
                TocExtension(slugify=slugify),
            ])
            # 设置过期时间的时候分散时间，不要设置成同一时间
            cache.set(md_key, (md.convert(obj.body), md.toc), 3600 * 24 + 10 * done_num)
            done_num += 1
    data = {'total': total_num, 'done': done_num}
    return data


def action_check_friend_links(site_link=None, white_list=None):
    """
    检查友链:
        1、检查当前显示的友链，请求友链，将非200的友链标记为不显示，并记录禁用原因
        2、检查当前不显示的友链，请求友链，将200返回的标记为显示，并删除禁用原因
        3、新增补充校验：可以添加参数site_link，则不仅仅校验网页是否打开200，还会校验网站中是否有site_link外链
    @return:
    """
    import re
    from blog.models import FriendLink

    white_list = white_list or []  # 设置白名单，不校验
    active_num = 0
    to_not_show = 0
    to_show = 0
    active_friend_list = FriendLink.objects.filter(is_active=True)
    for active_friend in active_friend_list:
        active_num += 1
        if active_friend.name in white_list:
            continue
        if active_friend.is_show is True:
            code, text = get_link_status(active_friend.link)
            if code != 200:
                active_friend.is_show = False
                active_friend.not_show_reason = f'网页请求返回{code}'
                active_friend.save(update_fields=['is_show', 'not_show_reason'])
                to_not_show += 1
            else:
                # 设置了网站参数则校验友链中是否包含本站外链
                if site_link:
                    site_check_result = re.findall(site_link, text)
                    if not site_check_result:
                        active_friend.is_show = False
                        active_friend.not_show_reason = f'网站未设置本站外链'
                        active_friend.save(update_fields=['is_show', 'not_show_reason'])
                        to_not_show += 1
        else:
            code, text = get_link_status(active_friend.link)
            if code == 200:
                if not site_link:
                    active_friend.is_show = True
                    active_friend.not_show_reason = ''
                    active_friend.save(update_fields=['is_show', 'not_show_reason'])
                    to_show += 1
                else:
                    site_check_result = re.findall(site_link, text)
                    if site_check_result:
                        active_friend.is_show = True
                        active_friend.not_show_reason = ''
                        active_friend.save(update_fields=['is_show', 'not_show_reason'])
                        to_show += 1
    data = {'active_num': active_num, 'to_not_show': to_not_show, 'to_show': to_show}
    return data


def action_clear_notification(day=200, is_read=True):
    """
    清理消息推送
    @param is_read: False表示清理所有，True表示只清理已读，默认清理已读
    @param day: 清理day天前的信息
    @return:
    """
    from django.db.models import Q
    from comment.models import Notification, SystemNotification

    current_date = datetime.now()
    delta = timedelta(days=day)
    past_date = current_date - delta
    if is_read is True:
        query = Q(create_date__lte=past_date, is_read=True)
    else:
        query = Q(create_date__lte=past_date)

    comment_notification_objects = Notification.objects.filter(query)
    system_notification_objects = SystemNotification.objects.filter(query)
    comment_num = comment_notification_objects.count()
    system_num = system_notification_objects.count()
    comment_notification_objects.delete()
    system_notification_objects.delete()
    return {'comment_num': comment_num, 'system_num': system_num}


def action_cleanup_task_result(day=3):
    """
    清理任务结果
    清理day天前成功或结束的，其他状态的一概不清理
    @return:
    """
    from django.db.models import Q
    from django_celery_results.models import TaskResult

    current_date = datetime.now()
    delta = timedelta(days=day)
    past_date = current_date - delta
    query = Q(date_done__lte=past_date)
    task_result_objects = TaskResult.objects.filter(query)
    task_result_count = task_result_objects.count()
    task_result_objects.delete()
    return {'task_result_count': task_result_count}


def action_baidu_push(baidu_url, months):
    """
    主动推送文章地址到百度，指定推送最近months月的文章链接
    @param baidu_url: 百度接口调用地址，包含token
    @param months: 几个月内的文章
    @return:
    """
    import requests
    from datetime import datetime
    from dateutil.relativedelta import relativedelta
    from blog.models import Article
    from blog.utils import site_full_url

    def baidu_push(urls):
        headers = {
            'User-Agent': 'curl/7.12.1',
            'Host': 'data.zz.baidu.com',
            'Content-Type': 'text/plain',
            'Content-Length': '83'
        }
        try:
            response = requests.post(baidu_url, headers=headers, data=urls, timeout=5)
            return True, response.json()
        except Exception as e:
            return False, e

    current_date = datetime.now()
    previous_date = current_date - relativedelta(months=months)
    article_list = Article.objects.filter(create_date__gte=previous_date, is_publish=True)
    article_count = article_list.count()
    if not article_count:
        return {'article_count': article_count, 'status': True, 'result': 'ignore'}
    url_list = [f'{site_full_url()}{each.get_absolute_url()}' for each in article_list]
    status, result = baidu_push('\n'.join(url_list))
    return {'article_count': article_count, 'status': status, 'result': result}


def action_check_site_links(white_domain_list=None):
    """
    校验导航网站有效性，只校验状态为True或者False的，为空的不校验，所以特殊地址可以设置成空跳过校验
    @param white_domain_list: 域名白名单
    @return:
    """
    from webstack.models import NavigationSite

    white_domain_list = white_domain_list or []
    active_num = 0
    to_not_show = 0
    to_show = 0
    active_site_list = NavigationSite.objects.filter(is_show__isnull=False)
    for site in active_site_list:
        active_num += 1
        # 当站点包含白名单域名则直接跳过校验
        if white_list_check(white_domain_list, site.link):
            continue
        if site.is_show is True:
            code, text = get_link_status(site.link)
            if code < 200 or code >= 400:
                site.is_show = False
                site.not_show_reason = f'网页请求返回{code}'
                site.save(update_fields=['is_show', 'not_show_reason'])
                to_not_show += 1
        else:
            code, text = get_link_status(site.link)
            if 200 <= code < 400:
                site.is_show = True
                site.not_show_reason = ''
                site.save(update_fields=['is_show', 'not_show_reason'])
                to_show += 1
    data = {'active_num': active_num, 'to_not_show': to_not_show, 'to_show': to_show}
    return data


def action_publish_article_by_task(article_ids):
    """
    定时将草稿发布出去
    @param article_ids: 需要发布的文章ID
    @return:
    """
    from blog.models import Article
    data = {}
    for each_id in article_ids:
        article = Article.objects.get(id=int(each_id))
        if article:
            if article.is_publish is False:
                article.is_publish = True
                article.save()
                data[each_id] = 'Article published successfully'
            else:
                data[each_id] = 'Article has been published'
        else:
            data[each_id] = 'Article not found'
    return data


def action_write_or_update_view():
    """
    写入或更新当天的文章阅读量
    @return:
    """
    from django.db.models import Sum
    from blog.models import Article, ArticleView, PageView
    date_value = datetime.today().strftime('%Y%m%d')
    this_hour = datetime.now().strftime('%H')
    total_views = Article.objects.aggregate(Sum('views'))['views__sum'] or 0
    article_views_dict = {}
    # 获取所有文章的id和views字段
    articles = Article.objects.all()
    # 将id和views存储在字典中
    for article in articles:
        article_views_dict[article.id] = article.views

    # 单页面的统计逻辑
    page_views_dict = {}
    page_total_views = PageView.objects.aggregate(Sum('views'))['views__sum'] or 0
    total_views += page_total_views  # 将文章和单页面的总访问量叠加
    for page in PageView.objects.all():
        page_views_dict[page.url] = page.views

    body_data = {
        'total_views': total_views,  # 当前阅读总计
        'today_views': article_views_dict,  # 当前阅读详情
        'page_views': page_views_dict,  # 单页面的阅读详情
        'every_hours': {}  # 当前每小时阅读统计
    }
    obj = ArticleView.objects.filter(date=date_value)
    if obj and json.loads(obj.first().body).get('every_hours'):
        every_hours = json.loads(obj.first().body).get('every_hours')
    else:
        every_hours = {}
    every_hours[this_hour] = total_views
    body_data['every_hours'] = every_hours

    body = json.dumps(body_data)
    # 写入或更新一条实例
    ArticleView.objects.update_or_create(date=date_value, defaults={'body': body})


class ArticleViewsTool:
    key = RedisKeys.views_statistics

    @staticmethod
    def get_last_week_dates():
        """
        获取上周日期列表
        @return:
        """
        today = datetime.today()
        last_monday = today - timedelta(days=(today.weekday() + 7))
        last_week_dates = [last_monday + timedelta(days=i) for i in range(7)]
        # 将日期格式化为字符串，并返回列表
        last_week_dates_str = [date.strftime('%Y%m%d') for date in last_week_dates]
        return last_week_dates_str

    @staticmethod
    def get_this_week_dates():
        """
        获取本周日期列表
        @return:
        """
        today = datetime.today()
        this_monday = today - timedelta(days=today.weekday())
        this_week_dates = [this_monday + timedelta(days=i) for i in range(today.weekday() + 1)]
        # 将日期格式化为字符串，并返回列表
        this_week_dates_str = [date.strftime('%Y%m%d') for date in this_week_dates]
        return this_week_dates_str

    @staticmethod
    def get_day_of_week(date_string):
        # 将输入的日期字符串转换为日期对象
        date_object = datetime.strptime(date_string, '%Y%m%d')
        # 获取星期几的数字（0代表星期一，1代表星期二，以此类推）
        day_of_week = date_object.weekday()
        # 映射数字到星期几的字符串
        days_of_week = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        day_str = days_of_week[day_of_week]

        return day_str

    @staticmethod
    def get_yesterday(date_string):
        # 将输入的日期字符串转换为日期对象
        date_object = datetime.strptime(date_string, '%Y%m%d')
        yesterday = date_object - timedelta(days=1)
        return yesterday.strftime('%Y%m%d')

    @staticmethod
    def get_date_total_views(date):
        """
        获取一个日期的阅读量总数，没有就返回0
        @param date: 20231208
        @return:
        """
        from blog.models import ArticleView
        obj = ArticleView.objects.filter(date=date)
        if obj:
            total_views = json.loads(obj.first().body)['total_views']
            return total_views
        return 0

    @staticmethod
    def get_hours_views(date):
        """
        获取一个日期的每小时的数据，没有则返回{}
        @param date:
        @return:
        """
        from blog.models import ArticleView
        obj = ArticleView.objects.filter(date=date)
        if obj and json.loads(obj.first().body).get('every_hours'):
            every_hours = json.loads(obj.first().body)['every_hours']
            return every_hours
        return {}

    def set_data_to_redis(self):
        """
        从ArticleView模型中获取数据，并分析入库到redis
        @return:
        """
        from django.core.cache import cache
        today_str = datetime.today().strftime('%Y%m%d')
        total_views = self.get_date_total_views(today_str)

        data = {
            'last_week_views': {},  # 上周数据
            'this_week_views': {},  # 本周数据
            'total_views': total_views,  # 当天当时数据
        }

        for last_day in self.get_last_week_dates():
            yesterday = self.get_yesterday(last_day)
            last_day_views = self.get_date_total_views(last_day)
            yesterday_views = self.get_date_total_views(yesterday)
            if last_day_views and yesterday_views:
                last_day_key = self.get_day_of_week(last_day)
                data['last_week_views'][last_day_key] = last_day_views - yesterday_views
        for this_day in self.get_this_week_dates():
            yesterday = self.get_yesterday(this_day)
            this_day_views = self.get_date_total_views(this_day)
            yesterday_views = self.get_date_total_views(yesterday)
            if this_day_views and yesterday_views:
                this_day_key = self.get_day_of_week(this_day)
                data['this_week_views'][this_day_key] = this_day_views - yesterday_views
        cache.set(self.key, data, 3600 * 24 * 7)
        return data


if __name__ == '__main__':
    import os
    import django
    from django.core.cache import cache

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'izone.settings')
    django.setup()

    # print(action_clear_notification(100))
    # print(action_cleanup_task_result(7))
    # print(action_check_site_links())
    cache.delete(RedisKeys.views_statistics)
    cache.delete(RedisKeys.hours_views_statistics.format(hour=datetime.now().strftime('%Y%m%d%H')))
    # action_write_or_update_view()
    print(ArticleViewsTool().set_data_to_redis())
