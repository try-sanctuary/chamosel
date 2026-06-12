<?php
/**
 * chamosel client for PHP scrapers.
 *
 * Routes requests through the HAProxy pool and rotates the exit IP via the
 * controller REST API when blocked. See README for the service overview.
 */
class ChamoselClient
{
    private string $proxy;    // http://127.0.0.1:8888
    private string $apiBase;  // http://127.0.0.1:8800

    public function __construct(string $host = '127.0.0.1', int $proxyPort = 8888, int $apiPort = 8800)
    {
        $this->proxy   = "http://{$host}:{$proxyPort}";
        $this->apiBase = "http://{$host}:{$apiPort}";
    }

    /** Fetch through the rotating proxy pool. Returns ['code','body','error']. */
    public function fetch(string $url, int $timeout = 30): array
    {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_PROXY          => $this->proxy,
            CURLOPT_TIMEOUT        => $timeout,
            // Fresh connection per request so HAProxy (mode tcp) can land it on a
            // different backend; keep-alive would pin one exit IP.
            CURLOPT_FORBID_REUSE   => true,
            CURLOPT_FRESH_CONNECT  => true,
        ]);
        $body = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $err  = curl_error($ch);
        curl_close($ch);
        return ['code' => $code, 'body' => $body, 'error' => $err];
    }

    /**
     * Fetch with automatic rotation on a ban. On 403/429 it rotates one
     * instance, waits for the tunnel to reconnect, and retries.
     */
    public function fetchWithRetry(string $url, int $maxRetries = 3, int $reconnectWait = 8): array
    {
        $res = $this->fetch($url);
        $attempts = 0;
        while (in_array($res['code'], [403, 429], true) && $attempts < $maxRetries) {
            $this->rotate();                 // get a fresh exit IP
            sleep($reconnectWait);           // let the tunnel come back up
            $res = $this->fetch($url);
            $attempts++;
        }
        return $res;
    }

    /** Rotate one random instance, a named one, or 'all'. Returns decoded JSON. */
    public function rotate(?string $instance = null): array
    {
        $path = $instance ? '/rotate/' . rawurlencode($instance) : '/rotate';
        return $this->apiPost($path);
    }

    /** Pool status: health + public IP + rotation counts per instance. */
    public function pool(): array
    {
        return json_decode(@file_get_contents($this->apiBase . '/pool'), true) ?? [];
    }

    private function apiPost(string $path): array
    {
        $ch = curl_init($this->apiBase . $path);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_POST           => true,
            CURLOPT_POSTFIELDS     => '',
            CURLOPT_TIMEOUT        => 20,
        ]);
        $out = curl_exec($ch);
        curl_close($ch);
        return json_decode($out, true) ?? [];
    }
}

// --- Example ---
// $client = new ChamoselClient();
// $res = $client->fetchWithRetry('https://ipinfo.io/ip');
// echo $res['body'] . PHP_EOL;
// print_r($client->pool());
