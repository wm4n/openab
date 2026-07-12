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
    pub mention_id: Option<String>,
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
            thread_id: None,
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

    let json = serde_json::to_string(&event).unwrap();
    info!(channel_id = %payload.channel_id, sender_id = %payload.sender_id, "custom webhook → gateway");
    let _ = state.event_tx.send(json);
    axum::http::StatusCode::OK
}
