from django.http import HttpResponse

def health_ok(request):
    return HttpResponse("OK", content_type="text/plain")
