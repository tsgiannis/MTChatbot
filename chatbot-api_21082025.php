<?php
/**
 * Plugin Name: Chatbot API
 * Description: REST API endpoint για το chatbot (σερβίρει JSON από uploads/chatbot/chatbot_data.json).
 * Version: 1.1.0
 * Author: You
 */

if ( ! defined( 'ABSPATH' ) ) exit;

// === Ρυθμίσεις Logging ===
define('CHATBOT_API_LOG', true); // <-- άλλαξε σε false για να απενεργοποιήσεις logs
define('CHATBOT_API_LOG_FILE', WP_CONTENT_DIR . '/chatbot_api.log');

// Helper function
function chatbot_api_log($msg) {
    if (CHATBOT_API_LOG) {
        $line = "[" . date("Y-m-d H:i:s") . "] " . $msg . "\n";
        error_log($line, 3, CHATBOT_API_LOG_FILE);
    }
}

// --- Εγγραφή route ---
add_action('rest_api_init', function () {
    register_rest_route('chatbot/v1', '/data', [
        'methods' => 'GET',
        'callback' => 'chatbot_api_callback',
        'permission_callback' => '__return_true'
    ]);
});

// --- Callback ---
function chatbot_api_callback(WP_REST_Request $request) {
    chatbot_api_log("Request received from IP: " . $_SERVER['REMOTE_ADDR']);

    $upload_dir = wp_upload_dir();
    $json_path  = trailingslashit($upload_dir['basedir']) . 'chatbot/chatbot_data.json';

    chatbot_api_log("Looking for JSON at: " . $json_path);

    if (!file_exists($json_path)) {
        chatbot_api_log("File not found: " . $json_path);
        return new WP_Error('not_found', 'Το chatbot_data.json δεν βρέθηκε', ['status' => 404]);
    }

    $json = file_get_contents($json_path);
    $data = json_decode($json, true);

    if (json_last_error() !== JSON_ERROR_NONE) {
        chatbot_api_log("JSON decode error: " . json_last_error_msg());
        return new WP_Error('json_error', 'Σφάλμα JSON: ' . json_last_error_msg(), ['status' => 500]);
    }

    chatbot_api_log("JSON served successfully (" . strlen($json) . " bytes)");

    // --- CORS Headers ---
    header("Access-Control-Allow-Origin: *");
    header("Access-Control-Allow-Methods: GET, OPTIONS");
    header("Access-Control-Allow-Headers: Content-Type");

    return rest_ensure_response($data);
}
