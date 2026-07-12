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
    /// If set, gateway stores event_id → callback_url and POSTs the agent's
    /// GatewayReply to this URL when a reply arrives for platform="custom".
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

    // Register callback URL so the reply handler can deliver results.
    if let Some(url) = payload.callback_url.filter(|s| !s.is_empty()) {
        let mut callbacks = state.custom_callbacks.lock().await;
        callbacks.insert(event.event_id.clone(), url);
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
