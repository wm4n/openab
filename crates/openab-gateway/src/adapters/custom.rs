use crate::schema::{ChannelInfo, GatewayEvent, SenderInfo};
use crate::AppState;
use axum::extract::State;
use axum::http::HeaderMap;
use axum::Json;
use serde::Deserialize;
use std::sync::Arc;
use tracing::{info, warn};

#[derive(Debug, Deserialize)]
pub struct CustomWebhookPayload {
    pub text: String,
    pub sender_id: String,
    pub channel_id: String,
    /// Per-task thread ID for session isolation. Use `task_id` from the caller.
    pub thread_id: Option<String>,
    pub mention_id: Option<String>,
    /// Callback URL for reply delivery. Only accepted when CUSTOM_CALLBACK_ORIGIN
    /// is configured and the URL starts with that trusted origin.
    pub callback_url: Option<String>,
}

pub async fn webhook(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(payload): Json<CustomWebhookPayload>,
) -> axum::http::StatusCode {
    if let Some(ref expected) = state.custom_webhook_token {
        let provided = headers
            .get(axum::http::header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.strip_prefix("Bearer "));
        if provided != Some(expected.as_str()) {
            warn!("custom webhook rejected: invalid or missing Bearer token");
            return axum::http::StatusCode::UNAUTHORIZED;
        }
    }

    let mentions = payload
        .mention_id
        .filter(|s| !s.is_empty())
        .map(|id| vec![id])
        .unwrap_or_default();

    let event = GatewayEvent::new(
        "custom",
        ChannelInfo {
            id: payload.channel_id.clone(),
            channel_type: "channel".into(),
            thread_id: payload.thread_id.clone(),
        },
        SenderInfo {
            id: payload.sender_id.clone(),
            name: "web-user".into(),
            display_name: "web-user".into(),
            is_bot: false,
        },
        &payload.text,
        &format!("custom-{}", uuid::Uuid::new_v4()),
        mentions,
    );

    // Validate and register callback URL against the configured trusted origin.
    // Arbitrary URLs are rejected to prevent SSRF: the gateway must not POST
    // agent output to caller-controlled, unvalidated targets.
    if let Some(url) = payload.callback_url.filter(|s| !s.is_empty()) {
        match &state.custom_callback_origin {
            Some(origin) if url.starts_with(origin.as_str()) => {
                let mut callbacks = state.custom_callbacks.lock().await;
                callbacks.insert(event.event_id.clone(), url);
            }
            Some(origin) => {
                warn!(
                    callback_url = %url,
                    allowed_origin = %origin,
                    "custom webhook: callback_url rejected — not in allowed origin"
                );
                return axum::http::StatusCode::BAD_REQUEST;
            }
            None => {
                warn!(
                    callback_url = %url,
                    "custom webhook: callback_url ignored — CUSTOM_CALLBACK_ORIGIN not configured"
                );
            }
        }
    }

    let json = serde_json::to_string(&event).unwrap();
    info!(
        channel_id = %payload.channel_id,
        thread_id = ?payload.thread_id,
        sender_id = %payload.sender_id,
        event_id = %event.event_id,
        "custom webhook → gateway"
    );
    let _ = state.event_tx.send(json);
    axum::http::StatusCode::OK
}
