import scrapy

class IpifySpider(scrapy.Spider):
    name = 'ipify'
    
    # Dictionary to buffer the log message of the first occurrence
    # Format: { '192.168.1.1': "Log string for Jar A..." }
    ip_buffer = {}

    def start_requests(self):
        url = 'http://ip-api.com/json'
        
        for i in range(100):
            yield scrapy.Request(url, callback=self.parse, dont_filter=True)

    def parse(self, response):
        jar_id = response.meta.get('cookiejar')
        data = response.json()
        ip = data['query']
        
        # Create the standard log string
        log_message = f"Jar ID: {jar_id} | Request successful! IP: {ip}"

        if ip in self.ip_buffer:
            # === DUPLICATE FOUND ===
            
            # 1. Retrieve the buffered message from the FIRST request
            first_msg = self.ip_buffer[ip]
            
            # If it hasn't been printed yet, print it now
            if first_msg:
                self.logger.info(first_msg)
                # Set to None so we don't print the first one again if a 3rd request comes
                self.ip_buffer[ip] = None
            
            # 2. Log the CURRENT request normally
            self.logger.info(log_message)
            
        else:
            # === FIRST TIME SEEING IP ===
            # Store the message in the buffer, but DO NOT log it yet.
            # If no other request comes with this IP, this message is never printed.
            self.ip_buffer[ip] = log_message

        yield data