# -*- coding: utf-8 -*-

def test_home_page(client):
    """اختبار أن الصفحة الرئيسية أو مسار الدخول يعمل ويستجيب بنجاح"""
    response = client.get('/login')
    # نتأكد أن الصفحة تفتح بشكل صحيح (رمز الاستجابة 200 أو إعادة توجيه 302)
    assert response.status_code in [200, 302]