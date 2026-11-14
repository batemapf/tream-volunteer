resource "aws_cloudfront_function" "routes" {
  name    = "${local.name}-routes"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      if (request.uri === '/admin/') {
        return {statusCode: 302, statusDescription: 'Found', headers: {location: {value: '/admin'}, 'x-robots-tag': {value: 'noindex, nofollow'}}};
      }
      if (request.uri === '/admin') request.uri = '/organizer.html';
      return request;
    }
  JS
}
