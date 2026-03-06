# my_app/templatetags/app_tags.py

from django import template
from django.utils.html import format_html

register = template.Library()

@register.simple_tag(takes_context=True)
def sortable_header(context, field_name, display_name):
    request = context['request']
    current_sort = request.GET.get('sort')
    current_order = request.GET.get('order', 'asc')

    # 새로운 정렬 순서 결정
    if field_name == current_sort and current_order == 'asc':
        next_order = 'desc'
    else:
        next_order = 'asc'

    # 아이콘 (화살표)
    icon = ''
    if field_name == current_sort:
        if current_order == 'asc':
            icon = ' ▲'
        else:
            icon = ' ▼'

    # 기존 쿼리 파라미터를 유지하면서 정렬 파라미터만 변경
    query_params = request.GET.copy()
    query_params['sort'] = field_name
    query_params['order'] = next_order
    
    url = f"?{query_params.urlencode()}"

    # 최종 HTML 생성 (<a> 태그)
    return format_html('<a href="{}" style="color: inherit; text-decoration: none;">{} {}</a>',
                    url,
                    display_name,
                    icon)


@register.filter
def humanize_kr_simple(value):
    try:
        # 입력값을 정수형으로 변환 시도
        value = int(value)
    except (ValueError, TypeError):
        return value  # 변환이 불가능하면 원래 값 반환

    if value is None:
        return ""
        
    trillion = 1_0000_0000_0000  # 1조
    billion = 1_0000_0000      # 1억
    
    if value >= trillion:
        # 조 단위, 소수점 첫째 자리까지 표시
        return f'{value / trillion:.1f}T'
    if value >= billion:
        # 억 단위, 정수로 표시하고 쉼표 추가
        return f'{round(value / billion):,}B'
    # 억 미만의 숫자는 쉼표만 추가하여 반환
    return f'{value:,}'


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)