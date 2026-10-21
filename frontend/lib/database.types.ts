// AUTO-GENERATED from Supabase schema via `mcp__supabase__generate_typescript_types`
// or `supabase gen types typescript --project-id <your-project-ref>`.
// DO NOT EDIT BY HAND — run `scripts/regen-db-types.sh` to refresh.
//
// Handwritten types for DB-backed shapes proved unreliable (Phase 30 post-mortem:
// three of four production crashes were frontend types lying about nullability).
// Import from this file instead of declaring the shape inline.

/* eslint-disable */

export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.4"
  }
  public: {
    Tables: {
      access_groups: {
        Row: {
          created_at: string | null
          description: string | null
          id: string
          is_default: boolean
          is_public: boolean
          name: string
          settings: Json | null
          twin_id: string
          updated_at: string | null
        }
        Insert: {
          created_at?: string | null
          description?: string | null
          id?: string
          is_default?: boolean
          is_public?: boolean
          name: string
          settings?: Json | null
          twin_id: string
          updated_at?: string | null
        }
        Update: {
          created_at?: string | null
          description?: string | null
          id?: string
          is_default?: boolean
          is_public?: boolean
          name?: string
          settings?: Json | null
          twin_id?: string
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "access_groups_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      adk_conversations: {
        Row: {
          created_at: string
          id: string
          metadata: Json
          share_token: string | null
          surface: string
          tenant_id: string | null
          twin_id: string
          updated_at: string
          user_id: string | null
        }
        Insert: {
          created_at?: string
          id?: string
          metadata?: Json
          share_token?: string | null
          surface: string
          tenant_id?: string | null
          twin_id: string
          updated_at?: string
          user_id?: string | null
        }
        Update: {
          created_at?: string
          id?: string
          metadata?: Json
          share_token?: string | null
          surface?: string
          tenant_id?: string | null
          twin_id?: string
          updated_at?: string
          user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "adk_conversations_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      adk_internal_metadata: {
        Row: {
          key: string
          value: string
        }
        Insert: {
          key: string
          value: string
        }
        Update: {
          key?: string
          value?: string
        }
        Relationships: []
      }
      adk_messages: {
        Row: {
          citations: Json
          content: string
          conversation_id: string
          created_at: string
          id: string
          metadata: Json
          role: string
          tenant_id: string | null
          twin_id: string
        }
        Insert: {
          citations?: Json
          content: string
          conversation_id: string
          created_at?: string
          id?: string
          metadata?: Json
          role: string
          tenant_id?: string | null
          twin_id: string
        }
        Update: {
          citations?: Json
          content?: string
          conversation_id?: string
          created_at?: string
          id?: string
          metadata?: Json
          role?: string
          tenant_id?: string | null
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "adk_messages_conversation_id_fkey"
            columns: ["conversation_id"]
            isOneToOne: false
            referencedRelation: "adk_conversations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "adk_messages_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      adk_persona_artifacts: {
        Row: {
          artifact_json: Json
          created_at: string
          id: string
          status: string
          tenant_id: string
          twin_id: string
          updated_at: string
          version: string
        }
        Insert: {
          artifact_json?: Json
          created_at?: string
          id?: string
          status?: string
          tenant_id: string
          twin_id: string
          updated_at?: string
          version: string
        }
        Update: {
          artifact_json?: Json
          created_at?: string
          id?: string
          status?: string
          tenant_id?: string
          twin_id?: string
          updated_at?: string
          version?: string
        }
        Relationships: [
          {
            foreignKeyName: "adk_persona_artifacts_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      adk_persona_quotes: {
        Row: {
          confidence: number
          context: string | null
          created_at: string
          id: string
          persona_artifact_id: string
          position: number
          quote_text: string
          source_id: string | null
          tenant_id: string
          twin_id: string
          updated_at: string
        }
        Insert: {
          confidence?: number
          context?: string | null
          created_at?: string
          id?: string
          persona_artifact_id: string
          position?: number
          quote_text: string
          source_id?: string | null
          tenant_id: string
          twin_id: string
          updated_at?: string
        }
        Update: {
          confidence?: number
          context?: string | null
          created_at?: string
          id?: string
          persona_artifact_id?: string
          position?: number
          quote_text?: string
          source_id?: string | null
          tenant_id?: string
          twin_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "adk_persona_quotes_persona_artifact_id_fkey"
            columns: ["persona_artifact_id"]
            isOneToOne: false
            referencedRelation: "adk_persona_artifacts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "adk_persona_quotes_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      adk_research_artifacts: {
        Row: {
          artifact_json: Json
          created_at: string
          id: string
          run_id: string
          tenant_id: string
          twin_id: string | null
          updated_at: string
        }
        Insert: {
          artifact_json?: Json
          created_at?: string
          id?: string
          run_id: string
          tenant_id: string
          twin_id?: string | null
          updated_at?: string
        }
        Update: {
          artifact_json?: Json
          created_at?: string
          id?: string
          run_id?: string
          tenant_id?: string
          twin_id?: string | null
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "adk_research_artifacts_run_id_fkey"
            columns: ["run_id"]
            isOneToOne: true
            referencedRelation: "adk_research_runs"
            referencedColumns: ["id"]
          },
        ]
      }
      adk_research_runs: {
        Row: {
          created_at: string
          error_message: string | null
          hints: Json
          id: string
          idempotency_key: string | null
          status: string
          subject_name: string
          tenant_id: string
          twin_id: string | null
          updated_at: string
          user_id: string | null
        }
        Insert: {
          created_at?: string
          error_message?: string | null
          hints?: Json
          id?: string
          idempotency_key?: string | null
          status?: string
          subject_name: string
          tenant_id: string
          twin_id?: string | null
          updated_at?: string
          user_id?: string | null
        }
        Update: {
          created_at?: string
          error_message?: string | null
          hints?: Json
          id?: string
          idempotency_key?: string | null
          status?: string
          subject_name?: string
          tenant_id?: string
          twin_id?: string | null
          updated_at?: string
          user_id?: string | null
        }
        Relationships: []
      }
      adk_sessions: {
        Row: {
          app_name: string
          created_at: string
          id: string
          session_json: Json
          tenant_id: string | null
          twin_id: string | null
          updated_at: string
          user_id: string
        }
        Insert: {
          app_name: string
          created_at?: string
          id: string
          session_json?: Json
          tenant_id?: string | null
          twin_id?: string | null
          updated_at?: string
          user_id: string
        }
        Update: {
          app_name?: string
          created_at?: string
          id?: string
          session_json?: Json
          tenant_id?: string | null
          twin_id?: string | null
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      answer_patches: {
        Row: {
          id: string
          new_answer: string
          patched_at: string | null
          patched_by: string | null
          previous_answer: string
          reason: string | null
          verified_qna_id: string
        }
        Insert: {
          id?: string
          new_answer: string
          patched_at?: string | null
          patched_by?: string | null
          previous_answer: string
          reason?: string | null
          verified_qna_id: string
        }
        Update: {
          id?: string
          new_answer?: string
          patched_at?: string | null
          patched_by?: string | null
          previous_answer?: string
          reason?: string | null
          verified_qna_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "answer_patches_patched_by_fkey"
            columns: ["patched_by"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "answer_patches_verified_qna_id_fkey"
            columns: ["verified_qna_id"]
            isOneToOne: false
            referencedRelation: "verified_qna"
            referencedColumns: ["id"]
          },
        ]
      }
      app_states: {
        Row: {
          app_name: string
          state: Json
          update_time: string
        }
        Insert: {
          app_name: string
          state: Json
          update_time: string
        }
        Update: {
          app_name?: string
          state?: Json
          update_time?: string
        }
        Relationships: []
      }
      audit_logs: {
        Row: {
          action: string
          actor_id: string | null
          created_at: string | null
          event_type: string
          id: string
          metadata: Json | null
          tenant_id: string
          twin_id: string | null
        }
        Insert: {
          action: string
          actor_id?: string | null
          created_at?: string | null
          event_type: string
          id?: string
          metadata?: Json | null
          tenant_id: string
          twin_id?: string | null
        }
        Update: {
          action?: string
          actor_id?: string | null
          created_at?: string | null
          event_type?: string
          id?: string
          metadata?: Json | null
          tenant_id?: string
          twin_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "audit_logs_actor_id_fkey"
            columns: ["actor_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "audit_logs_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "audit_logs_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      booking_requests: {
        Row: {
          approved_at: string | null
          conversation_id: string | null
          created_at: string | null
          event_link: string | null
          expires_at: string | null
          gcal_event_id: string | null
          id: string
          meet_link: string | null
          proposed_end: string
          proposed_start: string
          rejected_at: string | null
          rejection_reason: string | null
          slot_duration_minutes: number | null
          status: string | null
          twin_id: string
          updated_at: string | null
          visitor_email: string
          visitor_message: string | null
          visitor_name: string
          visitor_timezone: string | null
        }
        Insert: {
          approved_at?: string | null
          conversation_id?: string | null
          created_at?: string | null
          event_link?: string | null
          expires_at?: string | null
          gcal_event_id?: string | null
          id?: string
          meet_link?: string | null
          proposed_end: string
          proposed_start: string
          rejected_at?: string | null
          rejection_reason?: string | null
          slot_duration_minutes?: number | null
          status?: string | null
          twin_id: string
          updated_at?: string | null
          visitor_email: string
          visitor_message?: string | null
          visitor_name: string
          visitor_timezone?: string | null
        }
        Update: {
          approved_at?: string | null
          conversation_id?: string | null
          created_at?: string | null
          event_link?: string | null
          expires_at?: string | null
          gcal_event_id?: string | null
          id?: string
          meet_link?: string | null
          proposed_end?: string
          proposed_start?: string
          rejected_at?: string | null
          rejection_reason?: string | null
          slot_duration_minutes?: number | null
          status?: string | null
          twin_id?: string
          updated_at?: string | null
          visitor_email?: string
          visitor_message?: string | null
          visitor_name?: string
          visitor_timezone?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "booking_requests_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      chat_logs: {
        Row: {
          added_to_faq: boolean
          answer: string
          created_at: string
          id: string
          profile_id: string
          question: string
          session_id: string
        }
        Insert: {
          added_to_faq?: boolean
          answer: string
          created_at?: string
          id?: string
          profile_id: string
          question: string
          session_id: string
        }
        Update: {
          added_to_faq?: boolean
          answer?: string
          created_at?: string
          id?: string
          profile_id?: string
          question?: string
          session_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "chat_logs_profile_id_fkey"
            columns: ["profile_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      chunks: {
        Row: {
          content: string
          content_date: string | null
          created_at: string | null
          embedding: string | null
          id: string
          metadata: Json | null
          privacy_level: string
          source_id: string
          twin_id: string | null
          updated_at: string | null
          vector_id: string | null
        }
        Insert: {
          content: string
          content_date?: string | null
          created_at?: string | null
          embedding?: string | null
          id?: string
          metadata?: Json | null
          privacy_level?: string
          source_id: string
          twin_id?: string | null
          updated_at?: string | null
          vector_id?: string | null
        }
        Update: {
          content?: string
          content_date?: string | null
          created_at?: string | null
          embedding?: string | null
          id?: string
          metadata?: Json | null
          privacy_level?: string
          source_id?: string
          twin_id?: string | null
          updated_at?: string | null
          vector_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "chunks_source_id_fkey"
            columns: ["source_id"]
            isOneToOne: false
            referencedRelation: "sources"
            referencedColumns: ["id"]
          },
        ]
      }
      citations: {
        Row: {
          chunk_id: string | null
          citation_url: string | null
          created_at: string | null
          id: string
          source_id: string | null
          verified_qna_id: string
        }
        Insert: {
          chunk_id?: string | null
          citation_url?: string | null
          created_at?: string | null
          id?: string
          source_id?: string | null
          verified_qna_id: string
        }
        Update: {
          chunk_id?: string | null
          citation_url?: string | null
          created_at?: string | null
          id?: string
          source_id?: string | null
          verified_qna_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "citations_verified_qna_id_fkey"
            columns: ["verified_qna_id"]
            isOneToOne: false
            referencedRelation: "verified_qna"
            referencedColumns: ["id"]
          },
        ]
      }
      clarification_threads: {
        Row: {
          answer_text: string | null
          answered_at: string | null
          answered_by: string | null
          conversation_id: string | null
          created_at: string | null
          created_by: string | null
          id: string
          memory_write_proposal: Json | null
          mode: string
          options: Json | null
          original_query: string | null
          owner_memory_id: string | null
          question: string
          requested_by: string | null
          source_message_id: string | null
          status: string
          tenant_id: string
          twin_id: string
          updated_at: string | null
        }
        Insert: {
          answer_text?: string | null
          answered_at?: string | null
          answered_by?: string | null
          conversation_id?: string | null
          created_at?: string | null
          created_by?: string | null
          id?: string
          memory_write_proposal?: Json | null
          mode?: string
          options?: Json | null
          original_query?: string | null
          owner_memory_id?: string | null
          question: string
          requested_by?: string | null
          source_message_id?: string | null
          status?: string
          tenant_id: string
          twin_id: string
          updated_at?: string | null
        }
        Update: {
          answer_text?: string | null
          answered_at?: string | null
          answered_by?: string | null
          conversation_id?: string | null
          created_at?: string | null
          created_by?: string | null
          id?: string
          memory_write_proposal?: Json | null
          mode?: string
          options?: Json | null
          original_query?: string | null
          owner_memory_id?: string | null
          question?: string
          requested_by?: string | null
          source_message_id?: string | null
          status?: string
          tenant_id?: string
          twin_id?: string
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "clarification_threads_conversation_id_fkey"
            columns: ["conversation_id"]
            isOneToOne: false
            referencedRelation: "conversations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "clarification_threads_owner_memory_id_fkey"
            columns: ["owner_memory_id"]
            isOneToOne: false
            referencedRelation: "owner_beliefs"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "clarification_threads_source_message_id_fkey"
            columns: ["source_message_id"]
            isOneToOne: false
            referencedRelation: "messages"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "clarification_threads_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "clarification_threads_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      connected_accounts: {
        Row: {
          created_at: string | null
          id: string
          profile_snapshot: Json | null
          provider: string
          provider_user_id: string | null
          updated_at: string | null
          user_id: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          profile_snapshot?: Json | null
          provider: string
          provider_user_id?: string | null
          updated_at?: string | null
          user_id: string
        }
        Update: {
          created_at?: string | null
          id?: string
          profile_snapshot?: Json | null
          provider?: string
          provider_user_id?: string | null
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "connected_accounts_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
        ]
      }
      content_health_checks: {
        Row: {
          check_type: string
          created_at: string | null
          id: string
          message: string | null
          metadata: Json | null
          source_id: string
          status: string
          updated_at: string | null
        }
        Insert: {
          check_type: string
          created_at?: string | null
          id?: string
          message?: string | null
          metadata?: Json | null
          source_id: string
          status: string
          updated_at?: string | null
        }
        Update: {
          check_type?: string
          created_at?: string | null
          id?: string
          message?: string | null
          metadata?: Json | null
          source_id?: string
          status?: string
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "content_health_checks_source_id_fkey"
            columns: ["source_id"]
            isOneToOne: false
            referencedRelation: "sources"
            referencedColumns: ["id"]
          },
        ]
      }
      content_permissions: {
        Row: {
          content_id: string
          content_type: string
          created_at: string | null
          group_id: string
          id: string
          twin_id: string
        }
        Insert: {
          content_id: string
          content_type: string
          created_at?: string | null
          group_id: string
          id?: string
          twin_id: string
        }
        Update: {
          content_id?: string
          content_type?: string
          created_at?: string | null
          group_id?: string
          id?: string
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "content_permissions_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "access_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "content_permissions_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      conversation_response_audits: {
        Row: {
          artifacts_used: Json
          assistant_message_id: string | null
          citations: Json
          confidence_score: number | null
          conversation_id: string | null
          created_at: string
          escalation_reason: string | null
          id: string
          intent_label: string | null
          prompt_variant: string | null
          refusal_reason: string | null
          response_action: string
          retrieval_summary: Json
          routing_decision_id: string | null
          sources_used: Json
          spec_version: string | null
          tenant_id: string | null
          twin_id: string
          workflow_intent: string | null
        }
        Insert: {
          artifacts_used?: Json
          assistant_message_id?: string | null
          citations?: Json
          confidence_score?: number | null
          conversation_id?: string | null
          created_at?: string
          escalation_reason?: string | null
          id?: string
          intent_label?: string | null
          prompt_variant?: string | null
          refusal_reason?: string | null
          response_action?: string
          retrieval_summary?: Json
          routing_decision_id?: string | null
          sources_used?: Json
          spec_version?: string | null
          tenant_id?: string | null
          twin_id: string
          workflow_intent?: string | null
        }
        Update: {
          artifacts_used?: Json
          assistant_message_id?: string | null
          citations?: Json
          confidence_score?: number | null
          conversation_id?: string | null
          created_at?: string
          escalation_reason?: string | null
          id?: string
          intent_label?: string | null
          prompt_variant?: string | null
          refusal_reason?: string | null
          response_action?: string
          retrieval_summary?: Json
          routing_decision_id?: string | null
          sources_used?: Json
          spec_version?: string | null
          tenant_id?: string | null
          twin_id?: string
          workflow_intent?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "conversation_response_audits_assistant_message_id_fkey"
            columns: ["assistant_message_id"]
            isOneToOne: false
            referencedRelation: "messages"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "conversation_response_audits_conversation_id_fkey"
            columns: ["conversation_id"]
            isOneToOne: false
            referencedRelation: "conversations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "conversation_response_audits_routing_decision_id_fkey"
            columns: ["routing_decision_id"]
            isOneToOne: false
            referencedRelation: "conversation_routing_decisions"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "conversation_response_audits_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "conversation_response_audits_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      conversation_routing_decisions: {
        Row: {
          action: string
          chosen_workflow: string
          clarifying_questions: Json
          confidence: number
          conversation_id: string | null
          created_at: string
          id: string
          intent: string
          interaction_context: string | null
          message_id: string | null
          metadata: Json
          output_schema: string
          required_inputs_missing: Json
          router_mode: string | null
          tenant_id: string | null
          twin_id: string
        }
        Insert: {
          action?: string
          chosen_workflow: string
          clarifying_questions?: Json
          confidence?: number
          conversation_id?: string | null
          created_at?: string
          id?: string
          intent: string
          interaction_context?: string | null
          message_id?: string | null
          metadata?: Json
          output_schema: string
          required_inputs_missing?: Json
          router_mode?: string | null
          tenant_id?: string | null
          twin_id: string
        }
        Update: {
          action?: string
          chosen_workflow?: string
          clarifying_questions?: Json
          confidence?: number
          conversation_id?: string | null
          created_at?: string
          id?: string
          intent?: string
          interaction_context?: string | null
          message_id?: string | null
          metadata?: Json
          output_schema?: string
          required_inputs_missing?: Json
          router_mode?: string | null
          tenant_id?: string | null
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "conversation_routing_decisions_conversation_id_fkey"
            columns: ["conversation_id"]
            isOneToOne: false
            referencedRelation: "conversations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "conversation_routing_decisions_message_id_fkey"
            columns: ["message_id"]
            isOneToOne: false
            referencedRelation: "messages"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "conversation_routing_decisions_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "conversation_routing_decisions_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      conversations: {
        Row: {
          created_at: string | null
          group_id: string | null
          id: string
          interaction_context: string | null
          origin_endpoint: string | null
          share_link_id: string | null
          training_session_id: string | null
          twin_id: string
          user_id: string | null
        }
        Insert: {
          created_at?: string | null
          group_id?: string | null
          id?: string
          interaction_context?: string | null
          origin_endpoint?: string | null
          share_link_id?: string | null
          training_session_id?: string | null
          twin_id: string
          user_id?: string | null
        }
        Update: {
          created_at?: string | null
          group_id?: string | null
          id?: string
          interaction_context?: string | null
          origin_endpoint?: string | null
          share_link_id?: string | null
          training_session_id?: string | null
          twin_id?: string
          user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "conversations_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "access_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "conversations_training_session_id_fkey"
            columns: ["training_session_id"]
            isOneToOne: false
            referencedRelation: "training_sessions"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "conversations_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "conversations_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
        ]
      }
      crawl_failures: {
        Row: {
          artifact_path: string | null
          canonical_url: string
          crawl_id: string
          crawl_page_id: string
          created_at: string | null
          failure_category: string
          failure_reason: string
          failure_type: string
          id: string
          is_retryable: boolean | null
          url: string
        }
        Insert: {
          artifact_path?: string | null
          canonical_url: string
          crawl_id: string
          crawl_page_id: string
          created_at?: string | null
          failure_category: string
          failure_reason: string
          failure_type: string
          id?: string
          is_retryable?: boolean | null
          url: string
        }
        Update: {
          artifact_path?: string | null
          canonical_url?: string
          crawl_id?: string
          crawl_page_id?: string
          created_at?: string | null
          failure_category?: string
          failure_reason?: string
          failure_type?: string
          id?: string
          is_retryable?: boolean | null
          url?: string
        }
        Relationships: [
          {
            foreignKeyName: "crawl_failures_crawl_id_fkey"
            columns: ["crawl_id"]
            isOneToOne: false
            referencedRelation: "crawl_runs"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "crawl_failures_crawl_page_id_fkey"
            columns: ["crawl_page_id"]
            isOneToOne: false
            referencedRelation: "crawl_pages"
            referencedColumns: ["id"]
          },
        ]
      }
      crawl_pages: {
        Row: {
          canonical_url: string
          content_hash: string | null
          content_length: number | null
          crawl_id: string
          created_at: string | null
          error_category: string | null
          error_detail: string | null
          fetched_at: string | null
          id: string
          ingested_at: string | null
          metadata: Json | null
          normalized_artifact_path: string | null
          previous_content_hash: string | null
          previous_page_id: string | null
          raw_artifact_path: string | null
          removed_at: string | null
          retry_count: number | null
          snippet: string | null
          status: string
          updated_at: string | null
          url: string
          url_hash: string | null
        }
        Insert: {
          canonical_url: string
          content_hash?: string | null
          content_length?: number | null
          crawl_id: string
          created_at?: string | null
          error_category?: string | null
          error_detail?: string | null
          fetched_at?: string | null
          id?: string
          ingested_at?: string | null
          metadata?: Json | null
          normalized_artifact_path?: string | null
          previous_content_hash?: string | null
          previous_page_id?: string | null
          raw_artifact_path?: string | null
          removed_at?: string | null
          retry_count?: number | null
          snippet?: string | null
          status?: string
          updated_at?: string | null
          url: string
          url_hash?: string | null
        }
        Update: {
          canonical_url?: string
          content_hash?: string | null
          content_length?: number | null
          crawl_id?: string
          created_at?: string | null
          error_category?: string | null
          error_detail?: string | null
          fetched_at?: string | null
          id?: string
          ingested_at?: string | null
          metadata?: Json | null
          normalized_artifact_path?: string | null
          previous_content_hash?: string | null
          previous_page_id?: string | null
          raw_artifact_path?: string | null
          removed_at?: string | null
          retry_count?: number | null
          snippet?: string | null
          status?: string
          updated_at?: string | null
          url?: string
          url_hash?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "crawl_pages_crawl_id_fkey"
            columns: ["crawl_id"]
            isOneToOne: false
            referencedRelation: "crawl_runs"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "crawl_pages_previous_page_id_fkey"
            columns: ["previous_page_id"]
            isOneToOne: false
            referencedRelation: "crawl_pages"
            referencedColumns: ["id"]
          },
        ]
      }
      crawl_runs: {
        Row: {
          completed_at: string | null
          created_at: string | null
          exclude_patterns: Json | null
          failed_authentications: number | null
          id: string
          include_patterns: Json | null
          manifest_artifact_path: string | null
          max_depth: number | null
          max_pages: number | null
          pages_failed: number | null
          pages_found: number | null
          pages_ingested: number | null
          pages_unchanged: number | null
          previous_crawl_id: string | null
          safety_config: Json | null
          seed_urls: Json
          started_at: string | null
          status: string
          twin_id: string
          updated_at: string | null
          url_canonicalization_rules: Json | null
        }
        Insert: {
          completed_at?: string | null
          created_at?: string | null
          exclude_patterns?: Json | null
          failed_authentications?: number | null
          id?: string
          include_patterns?: Json | null
          manifest_artifact_path?: string | null
          max_depth?: number | null
          max_pages?: number | null
          pages_failed?: number | null
          pages_found?: number | null
          pages_ingested?: number | null
          pages_unchanged?: number | null
          previous_crawl_id?: string | null
          safety_config?: Json | null
          seed_urls: Json
          started_at?: string | null
          status?: string
          twin_id: string
          updated_at?: string | null
          url_canonicalization_rules?: Json | null
        }
        Update: {
          completed_at?: string | null
          created_at?: string | null
          exclude_patterns?: Json | null
          failed_authentications?: number | null
          id?: string
          include_patterns?: Json | null
          manifest_artifact_path?: string | null
          max_depth?: number | null
          max_pages?: number | null
          pages_failed?: number | null
          pages_found?: number | null
          pages_ingested?: number | null
          pages_unchanged?: number | null
          previous_crawl_id?: string | null
          safety_config?: Json | null
          seed_urls?: Json
          started_at?: string | null
          status?: string
          twin_id?: string
          updated_at?: string | null
          url_canonicalization_rules?: Json | null
        }
        Relationships: [
          {
            foreignKeyName: "crawl_runs_previous_crawl_id_fkey"
            columns: ["previous_crawl_id"]
            isOneToOne: false
            referencedRelation: "crawl_runs"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "crawl_runs_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      edges: {
        Row: {
          created_at: string | null
          description: string | null
          from_node_id: string
          id: string
          properties: Json | null
          to_node_id: string
          twin_id: string
          type: string
          weight: number | null
        }
        Insert: {
          created_at?: string | null
          description?: string | null
          from_node_id: string
          id?: string
          properties?: Json | null
          to_node_id: string
          twin_id: string
          type: string
          weight?: number | null
        }
        Update: {
          created_at?: string | null
          description?: string | null
          from_node_id?: string
          id?: string
          properties?: Json | null
          to_node_id?: string
          twin_id?: string
          type?: string
          weight?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "edges_from_node_id_fkey"
            columns: ["from_node_id"]
            isOneToOne: false
            referencedRelation: "nodes"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "edges_to_node_id_fkey"
            columns: ["to_node_id"]
            isOneToOne: false
            referencedRelation: "nodes"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "edges_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      escalation_replies: {
        Row: {
          content: string
          created_at: string | null
          escalation_id: string
          id: string
          owner_id: string | null
        }
        Insert: {
          content: string
          created_at?: string | null
          escalation_id: string
          id?: string
          owner_id?: string | null
        }
        Update: {
          content?: string
          created_at?: string | null
          escalation_id?: string
          id?: string
          owner_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "escalation_replies_escalation_id_fkey"
            columns: ["escalation_id"]
            isOneToOne: false
            referencedRelation: "escalations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "escalation_replies_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
        ]
      }
      escalations: {
        Row: {
          created_at: string | null
          id: string
          message_id: string
          resolved_at: string | null
          resolved_by: string | null
          status: string
          tenant_id: string
          twin_id: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          message_id: string
          resolved_at?: string | null
          resolved_by?: string | null
          status?: string
          tenant_id: string
          twin_id: string
        }
        Update: {
          created_at?: string | null
          id?: string
          message_id?: string
          resolved_at?: string | null
          resolved_by?: string | null
          status?: string
          tenant_id?: string
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "escalations_message_id_fkey"
            columns: ["message_id"]
            isOneToOne: false
            referencedRelation: "messages"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "escalations_resolved_by_fkey"
            columns: ["resolved_by"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "escalations_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "escalations_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      events: {
        Row: {
          app_name: string
          event_data: Json | null
          id: string
          invocation_id: string
          session_id: string
          timestamp: string
          user_id: string
        }
        Insert: {
          app_name: string
          event_data?: Json | null
          id: string
          invocation_id: string
          session_id: string
          timestamp: string
          user_id: string
        }
        Update: {
          app_name?: string
          event_data?: Json | null
          id?: string
          invocation_id?: string
          session_id?: string
          timestamp?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "events_app_name_user_id_session_id_fkey"
            columns: ["app_name", "user_id", "session_id"]
            isOneToOne: false
            referencedRelation: "sessions"
            referencedColumns: ["app_name", "user_id", "id"]
          },
        ]
      }
      governance_policies: {
        Row: {
          content: string
          created_at: string | null
          id: string
          is_active: boolean
          name: string
          policy_type: string
          tenant_id: string | null
          twin_id: string
          updated_at: string | null
        }
        Insert: {
          content: string
          created_at?: string | null
          id?: string
          is_active?: boolean
          name: string
          policy_type: string
          tenant_id?: string | null
          twin_id: string
          updated_at?: string | null
        }
        Update: {
          content?: string
          created_at?: string | null
          id?: string
          is_active?: boolean
          name?: string
          policy_type?: string
          tenant_id?: string | null
          twin_id?: string
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "governance_policies_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "governance_policies_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      graph_claims: {
        Row: {
          claim_id: string
          claim_text: string
          claim_type: string
          confidence: number
          content_hash: string
          correlation_id: string | null
          extracted_at: string
          graph_entity_id: string | null
          graph_entity_type: string | null
          group_id: string
          id: string
          source_ref: string
          source_type: string
          tenant_id: string
          twin_id: string
        }
        Insert: {
          claim_id: string
          claim_text: string
          claim_type: string
          confidence: number
          content_hash: string
          correlation_id?: string | null
          extracted_at?: string
          graph_entity_id?: string | null
          graph_entity_type?: string | null
          group_id: string
          id?: string
          source_ref: string
          source_type: string
          tenant_id: string
          twin_id: string
        }
        Update: {
          claim_id?: string
          claim_text?: string
          claim_type?: string
          confidence?: number
          content_hash?: string
          correlation_id?: string | null
          extracted_at?: string
          graph_entity_id?: string | null
          graph_entity_type?: string | null
          group_id?: string
          id?: string
          source_ref?: string
          source_type?: string
          tenant_id?: string
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "fk_tenant"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_twin"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      graph_context_snapshots: {
        Row: {
          claim_count: number
          correlation_id: string | null
          created_at: string
          episode_count: number
          expires_at: string
          group_id: string
          id: string
          refreshed_by: string | null
          snapshot_data: Json
          tenant_id: string
          twin_id: string
          version: number
        }
        Insert: {
          claim_count?: number
          correlation_id?: string | null
          created_at?: string
          episode_count?: number
          expires_at: string
          group_id: string
          id?: string
          refreshed_by?: string | null
          snapshot_data: Json
          tenant_id: string
          twin_id: string
          version?: number
        }
        Update: {
          claim_count?: number
          correlation_id?: string | null
          created_at?: string
          episode_count?: number
          expires_at?: string
          group_id?: string
          id?: string
          refreshed_by?: string | null
          snapshot_data?: Json
          tenant_id?: string
          twin_id?: string
          version?: number
        }
        Relationships: [
          {
            foreignKeyName: "fk_tenant"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_twin"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      graph_contradiction_queue: {
        Row: {
          confidence: number
          contradiction_id: string
          correlation_id: string | null
          detected_at: string
          existing_claim_id: string
          existing_claim_text: string
          explanation: string
          group_id: string
          id: string
          new_claim_id: string
          new_claim_text: string
          resolution: string | null
          review_notes: string | null
          reviewed_at: string | null
          reviewed_by: string | null
          severity: string
          status: string
          tenant_id: string
          twin_id: string
        }
        Insert: {
          confidence: number
          contradiction_id: string
          correlation_id?: string | null
          detected_at?: string
          existing_claim_id: string
          existing_claim_text: string
          explanation: string
          group_id: string
          id?: string
          new_claim_id: string
          new_claim_text: string
          resolution?: string | null
          review_notes?: string | null
          reviewed_at?: string | null
          reviewed_by?: string | null
          severity: string
          status?: string
          tenant_id: string
          twin_id: string
        }
        Update: {
          confidence?: number
          contradiction_id?: string
          correlation_id?: string | null
          detected_at?: string
          existing_claim_id?: string
          existing_claim_text?: string
          explanation?: string
          group_id?: string
          id?: string
          new_claim_id?: string
          new_claim_text?: string
          resolution?: string | null
          review_notes?: string | null
          reviewed_at?: string | null
          reviewed_by?: string | null
          severity?: string
          status?: string
          tenant_id?: string
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "fk_tenant"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "fk_twin"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      graph_extraction_cache: {
        Row: {
          claims: Json
          content_hash: string
          created_at: string | null
          extractor_version: string
          id: string
          scope_id: string | null
          source_ref: string
          tenant_id: string
          twin_id: string
          updated_at: string | null
        }
        Insert: {
          claims?: Json
          content_hash: string
          created_at?: string | null
          extractor_version?: string
          id?: string
          scope_id?: string | null
          source_ref: string
          tenant_id: string
          twin_id: string
          updated_at?: string | null
        }
        Update: {
          claims?: Json
          content_hash?: string
          created_at?: string | null
          extractor_version?: string
          id?: string
          scope_id?: string | null
          source_ref?: string
          tenant_id?: string
          twin_id?: string
          updated_at?: string | null
        }
        Relationships: []
      }
      graph_outbox: {
        Row: {
          attempt_count: number | null
          completed_at: string | null
          correlation_id: string | null
          created_at: string | null
          creator_id: string | null
          error_message: string | null
          failed_at: string | null
          id: string
          idempotency_key: string
          max_attempts: number | null
          next_attempt_after: string | null
          operation: string
          payload: Json
          priority: number | null
          scope_id: string | null
          status: string
          tenant_id: string
          twin_id: string
          updated_at: string | null
        }
        Insert: {
          attempt_count?: number | null
          completed_at?: string | null
          correlation_id?: string | null
          created_at?: string | null
          creator_id?: string | null
          error_message?: string | null
          failed_at?: string | null
          id?: string
          idempotency_key: string
          max_attempts?: number | null
          next_attempt_after?: string | null
          operation: string
          payload?: Json
          priority?: number | null
          scope_id?: string | null
          status?: string
          tenant_id: string
          twin_id: string
          updated_at?: string | null
        }
        Update: {
          attempt_count?: number | null
          completed_at?: string | null
          correlation_id?: string | null
          created_at?: string | null
          creator_id?: string | null
          error_message?: string | null
          failed_at?: string | null
          id?: string
          idempotency_key?: string
          max_attempts?: number | null
          next_attempt_after?: string | null
          operation?: string
          payload?: Json
          priority?: number | null
          scope_id?: string | null
          status?: string
          tenant_id?: string
          twin_id?: string
          updated_at?: string | null
        }
        Relationships: []
      }
      group_limits: {
        Row: {
          created_at: string | null
          group_id: string
          id: string
          limit_type: string
          limit_value: number
          updated_at: string | null
        }
        Insert: {
          created_at?: string | null
          group_id: string
          id?: string
          limit_type: string
          limit_value: number
          updated_at?: string | null
        }
        Update: {
          created_at?: string | null
          group_id?: string
          id?: string
          limit_type?: string
          limit_value?: number
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "group_limits_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "access_groups"
            referencedColumns: ["id"]
          },
        ]
      }
      group_memberships: {
        Row: {
          created_at: string | null
          group_id: string
          id: string
          is_active: boolean
          twin_id: string
          user_id: string
        }
        Insert: {
          created_at?: string | null
          group_id: string
          id?: string
          is_active?: boolean
          twin_id: string
          user_id: string
        }
        Update: {
          created_at?: string | null
          group_id?: string
          id?: string
          is_active?: boolean
          twin_id?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "group_memberships_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "access_groups"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "group_memberships_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "group_memberships_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
        ]
      }
      group_overrides: {
        Row: {
          created_at: string | null
          group_id: string
          id: string
          override_type: string
          override_value: Json
          updated_at: string | null
        }
        Insert: {
          created_at?: string | null
          group_id: string
          id?: string
          override_type: string
          override_value: Json
          updated_at?: string | null
        }
        Update: {
          created_at?: string | null
          group_id?: string
          id?: string
          override_type?: string
          override_value?: Json
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "group_overrides_group_id_fkey"
            columns: ["group_id"]
            isOneToOne: false
            referencedRelation: "access_groups"
            referencedColumns: ["id"]
          },
        ]
      }
      ingestion_logs: {
        Row: {
          created_at: string | null
          id: string
          log_level: string
          message: string
          metadata: Json | null
          source_id: string
          twin_id: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          log_level: string
          message: string
          metadata?: Json | null
          source_id: string
          twin_id: string
        }
        Update: {
          created_at?: string | null
          id?: string
          log_level?: string
          message?: string
          metadata?: Json | null
          source_id?: string
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "ingestion_logs_source_id_fkey"
            columns: ["source_id"]
            isOneToOne: false
            referencedRelation: "sources"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "ingestion_logs_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      interview_sessions: {
        Row: {
          asked_template_ids: string[] | null
          blueprint_json: Json | null
          clarification_attempts: number | null
          completed_at: string | null
          conversation_id: string | null
          created_at: string
          current_question_id: string | null
          duration_seconds: number | null
          ended_at: string | null
          id: string
          intent_confirmed: boolean | null
          intent_summary: string | null
          last_repair_strategy: string | null
          memories_extracted: number | null
          metadata: Json | null
          response_quality_scores: Json | null
          skipped_slots: string[] | null
          slots_filled: number | null
          stage: string
          started_at: string
          status: string | null
          total_required_slots: number | null
          transcript: Json | null
          turn_count: number | null
          twin_id: string | null
          updated_at: string
          user_id: string | null
        }
        Insert: {
          asked_template_ids?: string[] | null
          blueprint_json?: Json | null
          clarification_attempts?: number | null
          completed_at?: string | null
          conversation_id?: string | null
          created_at?: string
          current_question_id?: string | null
          duration_seconds?: number | null
          ended_at?: string | null
          id?: string
          intent_confirmed?: boolean | null
          intent_summary?: string | null
          last_repair_strategy?: string | null
          memories_extracted?: number | null
          metadata?: Json | null
          response_quality_scores?: Json | null
          skipped_slots?: string[] | null
          slots_filled?: number | null
          stage?: string
          started_at?: string
          status?: string | null
          total_required_slots?: number | null
          transcript?: Json | null
          turn_count?: number | null
          twin_id?: string | null
          updated_at?: string
          user_id?: string | null
        }
        Update: {
          asked_template_ids?: string[] | null
          blueprint_json?: Json | null
          clarification_attempts?: number | null
          completed_at?: string | null
          conversation_id?: string | null
          created_at?: string
          current_question_id?: string | null
          duration_seconds?: number | null
          ended_at?: string | null
          id?: string
          intent_confirmed?: boolean | null
          intent_summary?: string | null
          last_repair_strategy?: string | null
          memories_extracted?: number | null
          metadata?: Json | null
          response_quality_scores?: Json | null
          skipped_slots?: string[] | null
          slots_filled?: number | null
          stage?: string
          started_at?: string
          status?: string | null
          total_required_slots?: number | null
          transcript?: Json | null
          turn_count?: number | null
          twin_id?: string | null
          updated_at?: string
          user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "interview_sessions_conversation_id_fkey"
            columns: ["conversation_id"]
            isOneToOne: false
            referencedRelation: "conversations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "interview_sessions_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "interview_sessions_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
        ]
      }
      learning_inputs: {
        Row: {
          applied_at: string | null
          applied_persona_spec_version: string | null
          base_persona_spec_version: string | null
          created_at: string
          created_by: string | null
          id: string
          input_type: string
          payload: Json
          review_note: string | null
          source_conversation_id: string | null
          source_message_id: string | null
          status: string
          tenant_id: string | null
          twin_id: string
          updated_at: string
        }
        Insert: {
          applied_at?: string | null
          applied_persona_spec_version?: string | null
          base_persona_spec_version?: string | null
          created_at?: string
          created_by?: string | null
          id?: string
          input_type: string
          payload?: Json
          review_note?: string | null
          source_conversation_id?: string | null
          source_message_id?: string | null
          status?: string
          tenant_id?: string | null
          twin_id: string
          updated_at?: string
        }
        Update: {
          applied_at?: string | null
          applied_persona_spec_version?: string | null
          base_persona_spec_version?: string | null
          created_at?: string
          created_by?: string | null
          id?: string
          input_type?: string
          payload?: Json
          review_note?: string | null
          source_conversation_id?: string | null
          source_message_id?: string | null
          status?: string
          tenant_id?: string | null
          twin_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "learning_inputs_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "learning_inputs_source_conversation_id_fkey"
            columns: ["source_conversation_id"]
            isOneToOne: false
            referencedRelation: "conversations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "learning_inputs_source_message_id_fkey"
            columns: ["source_message_id"]
            isOneToOne: false
            referencedRelation: "messages"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "learning_inputs_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "learning_inputs_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      meeting_analytics: {
        Row: {
          created_at: string
          filler_word_count: number | null
          id: string
          meeting_id: string
          participant_name: string
          sentiment_label: string | null
          sentiment_score: number | null
          talk_time_pct: number | null
          talk_time_seconds: number | null
          tenant_id: string
          word_count: number | null
          words_per_minute: number | null
        }
        Insert: {
          created_at?: string
          filler_word_count?: number | null
          id?: string
          meeting_id: string
          participant_name: string
          sentiment_label?: string | null
          sentiment_score?: number | null
          talk_time_pct?: number | null
          talk_time_seconds?: number | null
          tenant_id: string
          word_count?: number | null
          words_per_minute?: number | null
        }
        Update: {
          created_at?: string
          filler_word_count?: number | null
          id?: string
          meeting_id?: string
          participant_name?: string
          sentiment_label?: string | null
          sentiment_score?: number | null
          talk_time_pct?: number | null
          talk_time_seconds?: number | null
          tenant_id?: string
          word_count?: number | null
          words_per_minute?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "meeting_analytics_meeting_id_fkey"
            columns: ["meeting_id"]
            isOneToOne: false
            referencedRelation: "meetings"
            referencedColumns: ["id"]
          },
        ]
      }
      meeting_entities: {
        Row: {
          created_at: string
          entity_type: string
          entity_value: string
          id: string
          meeting_id: string
          tenant_id: string
          twin_id: string
        }
        Insert: {
          created_at?: string
          entity_type: string
          entity_value: string
          id?: string
          meeting_id: string
          tenant_id: string
          twin_id: string
        }
        Update: {
          created_at?: string
          entity_type?: string
          entity_value?: string
          id?: string
          meeting_id?: string
          tenant_id?: string
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "meeting_entities_meeting_id_fkey"
            columns: ["meeting_id"]
            isOneToOne: false
            referencedRelation: "meetings"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "meeting_entities_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      meeting_notifications: {
        Row: {
          created_at: string
          error_message: string | null
          id: string
          meeting_id: string | null
          notification_type: string
          resend_message_id: string | null
          sent_at: string | null
          status: string
          tenant_id: string
          twin_id: string
          week_of: string | null
        }
        Insert: {
          created_at?: string
          error_message?: string | null
          id?: string
          meeting_id?: string | null
          notification_type: string
          resend_message_id?: string | null
          sent_at?: string | null
          status?: string
          tenant_id: string
          twin_id: string
          week_of?: string | null
        }
        Update: {
          created_at?: string
          error_message?: string | null
          id?: string
          meeting_id?: string | null
          notification_type?: string
          resend_message_id?: string | null
          sent_at?: string | null
          status?: string
          tenant_id?: string
          twin_id?: string
          week_of?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "meeting_notifications_meeting_id_fkey"
            columns: ["meeting_id"]
            isOneToOne: false
            referencedRelation: "meetings"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "meeting_notifications_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      meeting_participants: {
        Row: {
          created_at: string
          id: string
          is_host: boolean | null
          meeting_id: string
          participant_email: string | null
          participant_name: string | null
          talk_time_seconds: number | null
          word_count: number | null
        }
        Insert: {
          created_at?: string
          id?: string
          is_host?: boolean | null
          meeting_id: string
          participant_email?: string | null
          participant_name?: string | null
          talk_time_seconds?: number | null
          word_count?: number | null
        }
        Update: {
          created_at?: string
          id?: string
          is_host?: boolean | null
          meeting_id?: string
          participant_email?: string | null
          participant_name?: string | null
          talk_time_seconds?: number | null
          word_count?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "meeting_participants_meeting_id_fkey"
            columns: ["meeting_id"]
            isOneToOne: false
            referencedRelation: "meetings"
            referencedColumns: ["id"]
          },
        ]
      }
      meeting_transcript_live: {
        Row: {
          bot_id: string
          created_at: string
          id: string
          speaker: string | null
          text: string
          timestamp: string | null
        }
        Insert: {
          bot_id: string
          created_at?: string
          id?: string
          speaker?: string | null
          text: string
          timestamp?: string | null
        }
        Update: {
          bot_id?: string
          created_at?: string
          id?: string
          speaker?: string | null
          text?: string
          timestamp?: string | null
        }
        Relationships: []
      }
      meeting_twin_responses: {
        Row: {
          confidence: number | null
          created_at: string
          id: string
          is_deferral: boolean
          meeting_id: string
          question_text: string | null
          responded_at: string
          response_text: string
          sources: Json | null
          turn_seq: number
          twin_id: string
        }
        Insert: {
          confidence?: number | null
          created_at?: string
          id?: string
          is_deferral?: boolean
          meeting_id: string
          question_text?: string | null
          responded_at: string
          response_text: string
          sources?: Json | null
          turn_seq: number
          twin_id: string
        }
        Update: {
          confidence?: number | null
          created_at?: string
          id?: string
          is_deferral?: boolean
          meeting_id?: string
          question_text?: string | null
          responded_at?: string
          response_text?: string
          sources?: Json | null
          turn_seq?: number
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "meeting_twin_responses_meeting_id_fkey"
            columns: ["meeting_id"]
            isOneToOne: false
            referencedRelation: "meetings"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "meeting_twin_responses_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      meetings: {
        Row: {
          action_items: Json | null
          booking_id: string | null
          context_prep: Json | null
          created_at: string
          duration_seconds: number | null
          id: string
          meet_link: string | null
          meeting_end: string | null
          meeting_start: string | null
          recall_bot_id: string | null
          status: string
          summary: string | null
          summary_json: Json | null
          tenant_id: string
          title: string | null
          transcript_raw: Json | null
          transcript_text: string | null
          twin_attends: boolean
          twin_id: string
          updated_at: string
        }
        Insert: {
          action_items?: Json | null
          booking_id?: string | null
          context_prep?: Json | null
          created_at?: string
          duration_seconds?: number | null
          id?: string
          meet_link?: string | null
          meeting_end?: string | null
          meeting_start?: string | null
          recall_bot_id?: string | null
          status?: string
          summary?: string | null
          summary_json?: Json | null
          tenant_id: string
          title?: string | null
          transcript_raw?: Json | null
          transcript_text?: string | null
          twin_attends?: boolean
          twin_id: string
          updated_at?: string
        }
        Update: {
          action_items?: Json | null
          booking_id?: string | null
          context_prep?: Json | null
          created_at?: string
          duration_seconds?: number | null
          id?: string
          meet_link?: string | null
          meeting_end?: string | null
          meeting_start?: string | null
          recall_bot_id?: string | null
          status?: string
          summary?: string | null
          summary_json?: Json | null
          tenant_id?: string
          title?: string | null
          transcript_raw?: Json | null
          transcript_text?: string | null
          twin_attends?: boolean
          twin_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "meetings_booking_id_fkey"
            columns: ["booking_id"]
            isOneToOne: false
            referencedRelation: "booking_requests"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "meetings_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      memory_events: {
        Row: {
          created_at: string | null
          event_type: string
          id: string
          payload: Json
          source_id: string | null
          source_type: string | null
          status: string
          tenant_id: string
          twin_id: string
        }
        Insert: {
          created_at?: string | null
          event_type: string
          id?: string
          payload?: Json
          source_id?: string | null
          source_type?: string | null
          status?: string
          tenant_id: string
          twin_id: string
        }
        Update: {
          created_at?: string | null
          event_type?: string
          id?: string
          payload?: Json
          source_id?: string | null
          source_type?: string | null
          status?: string
          tenant_id?: string
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "memory_events_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      messages: {
        Row: {
          citations: Json | null
          confidence_score: number | null
          content: string
          conversation_id: string
          created_at: string | null
          id: string
          interaction_context: string | null
          role: string
        }
        Insert: {
          citations?: Json | null
          confidence_score?: number | null
          content: string
          conversation_id: string
          created_at?: string | null
          id?: string
          interaction_context?: string | null
          role: string
        }
        Update: {
          citations?: Json | null
          confidence_score?: number | null
          content?: string
          conversation_id?: string
          created_at?: string | null
          id?: string
          interaction_context?: string | null
          role?: string
        }
        Relationships: [
          {
            foreignKeyName: "messages_conversation_id_fkey"
            columns: ["conversation_id"]
            isOneToOne: false
            referencedRelation: "conversations"
            referencedColumns: ["id"]
          },
        ]
      }
      name_deep_research_artifacts: {
        Row: {
          created_at: string
          id: string
          result_json: Json
          run_id: string
          schema_version: string
          tenant_id: string
          updated_at: string
        }
        Insert: {
          created_at?: string
          id?: string
          result_json: Json
          run_id: string
          schema_version?: string
          tenant_id: string
          updated_at?: string
        }
        Update: {
          created_at?: string
          id?: string
          result_json?: Json
          run_id?: string
          schema_version?: string
          tenant_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "name_deep_research_artifacts_run_id_fkey"
            columns: ["run_id"]
            isOneToOne: true
            referencedRelation: "name_deep_research_runs"
            referencedColumns: ["id"]
          },
        ]
      }
      name_deep_research_pages: {
        Row: {
          canonical_url: string
          content_hash: string | null
          created_at: string
          extracted_text: string
          extracted_word_count: number
          id: string
          metadata: Json
          run_id: string
          source_id: string | null
          tenant_id: string
          updated_at: string
        }
        Insert: {
          canonical_url: string
          content_hash?: string | null
          created_at?: string
          extracted_text?: string
          extracted_word_count?: number
          id?: string
          metadata?: Json
          run_id: string
          source_id?: string | null
          tenant_id: string
          updated_at?: string
        }
        Update: {
          canonical_url?: string
          content_hash?: string | null
          created_at?: string
          extracted_text?: string
          extracted_word_count?: number
          id?: string
          metadata?: Json
          run_id?: string
          source_id?: string | null
          tenant_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "name_deep_research_pages_run_id_fkey"
            columns: ["run_id"]
            isOneToOne: false
            referencedRelation: "name_deep_research_runs"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "name_deep_research_pages_source_id_fkey"
            columns: ["source_id"]
            isOneToOne: false
            referencedRelation: "name_deep_research_sources"
            referencedColumns: ["id"]
          },
        ]
      }
      name_deep_research_runs: {
        Row: {
          created_at: string
          created_by: string
          error_message: string | null
          id: string
          idempotency_key: string | null
          input_company: string | null
          input_location: string | null
          input_name: string
          input_website: string | null
          queries_used: Json
          run_completed_at: string | null
          run_started_at: string | null
          selected_model: string | null
          sources_used_in_final: number
          status: string
          tenant_id: string
          twin_id: string | null
          updated_at: string
          urls_blocked: number
          urls_considered: number
          urls_crawled: number
          words_extracted: number
        }
        Insert: {
          created_at?: string
          created_by: string
          error_message?: string | null
          id?: string
          idempotency_key?: string | null
          input_company?: string | null
          input_location?: string | null
          input_name: string
          input_website?: string | null
          queries_used?: Json
          run_completed_at?: string | null
          run_started_at?: string | null
          selected_model?: string | null
          sources_used_in_final?: number
          status?: string
          tenant_id: string
          twin_id?: string | null
          updated_at?: string
          urls_blocked?: number
          urls_considered?: number
          urls_crawled?: number
          words_extracted?: number
        }
        Update: {
          created_at?: string
          created_by?: string
          error_message?: string | null
          id?: string
          idempotency_key?: string | null
          input_company?: string | null
          input_location?: string | null
          input_name?: string
          input_website?: string | null
          queries_used?: Json
          run_completed_at?: string | null
          run_started_at?: string | null
          selected_model?: string | null
          sources_used_in_final?: number
          status?: string
          tenant_id?: string
          twin_id?: string | null
          updated_at?: string
          urls_blocked?: number
          urls_considered?: number
          urls_crawled?: number
          words_extracted?: number
        }
        Relationships: []
      }
      name_deep_research_sources: {
        Row: {
          blocked_reason: string | null
          canonical_url: string
          content_quality: string
          created_at: string
          id: string
          identity_match_confidence: number
          metadata: Json
          published_at: string | null
          retrieved_at: string
          run_id: string
          source_type: string
          tenant_id: string
          title: string | null
          updated_at: string
          url: string
          used_in_final: boolean
        }
        Insert: {
          blocked_reason?: string | null
          canonical_url: string
          content_quality?: string
          created_at?: string
          id?: string
          identity_match_confidence?: number
          metadata?: Json
          published_at?: string | null
          retrieved_at?: string
          run_id: string
          source_type?: string
          tenant_id: string
          title?: string | null
          updated_at?: string
          url: string
          used_in_final?: boolean
        }
        Update: {
          blocked_reason?: string | null
          canonical_url?: string
          content_quality?: string
          created_at?: string
          id?: string
          identity_match_confidence?: number
          metadata?: Json
          published_at?: string | null
          retrieved_at?: string
          run_id?: string
          source_type?: string
          tenant_id?: string
          title?: string | null
          updated_at?: string
          url?: string
          used_in_final?: boolean
        }
        Relationships: [
          {
            foreignKeyName: "name_deep_research_sources_run_id_fkey"
            columns: ["run_id"]
            isOneToOne: false
            referencedRelation: "name_deep_research_runs"
            referencedColumns: ["id"]
          },
        ]
      }
      nodes: {
        Row: {
          created_at: string | null
          description: string | null
          id: string
          name: string
          properties: Json | null
          status: string | null
          twin_id: string
          type: string
          updated_at: string | null
        }
        Insert: {
          created_at?: string | null
          description?: string | null
          id?: string
          name: string
          properties?: Json | null
          status?: string | null
          twin_id: string
          type: string
          updated_at?: string | null
        }
        Update: {
          created_at?: string | null
          description?: string | null
          id?: string
          name?: string
          properties?: Json | null
          status?: string | null
          twin_id?: string
          type?: string
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "nodes_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      owner_beliefs: {
        Row: {
          confidence: number | null
          created_at: string | null
          embedding: Json | null
          id: string
          intensity: number | null
          memory_type: string
          provenance: Json | null
          stance: string | null
          status: string
          superseded_by: string | null
          tenant_id: string
          topic_normalized: string
          twin_id: string
          updated_at: string | null
          value: string
        }
        Insert: {
          confidence?: number | null
          created_at?: string | null
          embedding?: Json | null
          id?: string
          intensity?: number | null
          memory_type: string
          provenance?: Json | null
          stance?: string | null
          status?: string
          superseded_by?: string | null
          tenant_id: string
          topic_normalized: string
          twin_id: string
          updated_at?: string | null
          value: string
        }
        Update: {
          confidence?: number | null
          created_at?: string | null
          embedding?: Json | null
          id?: string
          intensity?: number | null
          memory_type?: string
          provenance?: Json | null
          stance?: string | null
          status?: string
          superseded_by?: string | null
          tenant_id?: string
          topic_normalized?: string
          twin_id?: string
          updated_at?: string | null
          value?: string
        }
        Relationships: [
          {
            foreignKeyName: "owner_beliefs_superseded_by_fkey"
            columns: ["superseded_by"]
            isOneToOne: false
            referencedRelation: "owner_beliefs"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "owner_beliefs_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "owner_beliefs_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      owner_review_queue: {
        Row: {
          conversation_id: string | null
          created_at: string
          id: string
          message_id: string | null
          payload: Json
          priority: string
          reason: string
          resolved_at: string | null
          resolved_by: string | null
          routing_decision_id: string | null
          status: string
          tenant_id: string | null
          twin_id: string
          updated_at: string
        }
        Insert: {
          conversation_id?: string | null
          created_at?: string
          id?: string
          message_id?: string | null
          payload?: Json
          priority?: string
          reason: string
          resolved_at?: string | null
          resolved_by?: string | null
          routing_decision_id?: string | null
          status?: string
          tenant_id?: string | null
          twin_id: string
          updated_at?: string
        }
        Update: {
          conversation_id?: string | null
          created_at?: string
          id?: string
          message_id?: string | null
          payload?: Json
          priority?: string
          reason?: string
          resolved_at?: string | null
          resolved_by?: string | null
          routing_decision_id?: string | null
          status?: string
          tenant_id?: string | null
          twin_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "owner_review_queue_conversation_id_fkey"
            columns: ["conversation_id"]
            isOneToOne: false
            referencedRelation: "conversations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "owner_review_queue_message_id_fkey"
            columns: ["message_id"]
            isOneToOne: false
            referencedRelation: "messages"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "owner_review_queue_resolved_by_fkey"
            columns: ["resolved_by"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "owner_review_queue_routing_decision_id_fkey"
            columns: ["routing_decision_id"]
            isOneToOne: false
            referencedRelation: "conversation_routing_decisions"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "owner_review_queue_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "owner_review_queue_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      persona_decision_traces: {
        Row: {
          clause_ids: string[]
          created_at: string
          id: string
          intent_label: string | null
          metadata: Json
          options: Json
          owner_id: string
          prompt: string
          rationale: string | null
          scenario_id: string | null
          selected_option: string
          tenant_id: string | null
          thresholds: Json
          training_session_id: string
          twin_id: string
          updated_at: string
        }
        Insert: {
          clause_ids?: string[]
          created_at?: string
          id?: string
          intent_label?: string | null
          metadata?: Json
          options?: Json
          owner_id: string
          prompt: string
          rationale?: string | null
          scenario_id?: string | null
          selected_option: string
          tenant_id?: string | null
          thresholds?: Json
          training_session_id: string
          twin_id: string
          updated_at?: string
        }
        Update: {
          clause_ids?: string[]
          created_at?: string
          id?: string
          intent_label?: string | null
          metadata?: Json
          options?: Json
          owner_id?: string
          prompt?: string
          rationale?: string | null
          scenario_id?: string | null
          selected_option?: string
          tenant_id?: string | null
          thresholds?: Json
          training_session_id?: string
          twin_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "persona_decision_traces_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_decision_traces_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_decision_traces_training_session_id_fkey"
            columns: ["training_session_id"]
            isOneToOne: false
            referencedRelation: "training_sessions"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_decision_traces_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      persona_feedback_learning_runs: {
        Row: {
          avg_confidence_delta: number | null
          completed_at: string | null
          created_at: string
          created_by: string | null
          events_scanned: number
          gate_summary: Json
          id: string
          modules_updated: number
          publish_candidate_version: string | null
          publish_decision: string
          started_at: string
          status: string
          summary: Json
          tenant_id: string | null
          twin_id: string
          updated_at: string
        }
        Insert: {
          avg_confidence_delta?: number | null
          completed_at?: string | null
          created_at?: string
          created_by?: string | null
          events_scanned?: number
          gate_summary?: Json
          id?: string
          modules_updated?: number
          publish_candidate_version?: string | null
          publish_decision?: string
          started_at?: string
          status?: string
          summary?: Json
          tenant_id?: string | null
          twin_id: string
          updated_at?: string
        }
        Update: {
          avg_confidence_delta?: number | null
          completed_at?: string | null
          created_at?: string
          created_by?: string | null
          events_scanned?: number
          gate_summary?: Json
          id?: string
          modules_updated?: number
          publish_candidate_version?: string | null
          publish_decision?: string
          started_at?: string
          status?: string
          summary?: Json
          tenant_id?: string | null
          twin_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "persona_feedback_learning_runs_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_feedback_learning_runs_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_feedback_learning_runs_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      persona_introspection: {
        Row: {
          answer: string
          clause_ids: string[]
          created_at: string
          id: string
          intent_label: string | null
          metadata: Json
          owner_id: string
          question: string
          tenant_id: string | null
          thresholds: Json
          training_session_id: string
          twin_id: string
          updated_at: string
        }
        Insert: {
          answer: string
          clause_ids?: string[]
          created_at?: string
          id?: string
          intent_label?: string | null
          metadata?: Json
          owner_id: string
          question: string
          tenant_id?: string | null
          thresholds?: Json
          training_session_id: string
          twin_id: string
          updated_at?: string
        }
        Update: {
          answer?: string
          clause_ids?: string[]
          created_at?: string
          id?: string
          intent_label?: string | null
          metadata?: Json
          owner_id?: string
          question?: string
          tenant_id?: string | null
          thresholds?: Json
          training_session_id?: string
          twin_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "persona_introspection_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_introspection_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_introspection_training_session_id_fkey"
            columns: ["training_session_id"]
            isOneToOne: false
            referencedRelation: "training_sessions"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_introspection_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      persona_judge_results: {
        Row: {
          conversation_id: string | null
          created_at: string
          deterministic_gate_passed: boolean
          draft_persona_score: number
          final_persona_score: number
          id: string
          intent_label: string
          interaction_context: string | null
          module_ids: string[]
          persona_spec_version: string | null
          rewrite_applied: boolean
          rewrite_directives: string[]
          rewrite_reason_categories: string[]
          structure_policy_passed: boolean
          structure_policy_score: number
          tenant_id: string | null
          twin_id: string
          violated_clause_ids: string[]
          voice_passed: boolean
          voice_score: number
        }
        Insert: {
          conversation_id?: string | null
          created_at?: string
          deterministic_gate_passed?: boolean
          draft_persona_score?: number
          final_persona_score?: number
          id?: string
          intent_label: string
          interaction_context?: string | null
          module_ids?: string[]
          persona_spec_version?: string | null
          rewrite_applied?: boolean
          rewrite_directives?: string[]
          rewrite_reason_categories?: string[]
          structure_policy_passed?: boolean
          structure_policy_score?: number
          tenant_id?: string | null
          twin_id: string
          violated_clause_ids?: string[]
          voice_passed?: boolean
          voice_score?: number
        }
        Update: {
          conversation_id?: string | null
          created_at?: string
          deterministic_gate_passed?: boolean
          draft_persona_score?: number
          final_persona_score?: number
          id?: string
          intent_label?: string
          interaction_context?: string | null
          module_ids?: string[]
          persona_spec_version?: string | null
          rewrite_applied?: boolean
          rewrite_directives?: string[]
          rewrite_reason_categories?: string[]
          structure_policy_passed?: boolean
          structure_policy_score?: number
          tenant_id?: string | null
          twin_id?: string
          violated_clause_ids?: string[]
          voice_passed?: boolean
          voice_score?: number
        }
        Relationships: [
          {
            foreignKeyName: "persona_judge_results_conversation_id_fkey"
            columns: ["conversation_id"]
            isOneToOne: false
            referencedRelation: "conversations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_judge_results_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_judge_results_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      persona_modules: {
        Row: {
          confidence: number | null
          created_at: string
          id: string
          intent_label: string | null
          module_data: Json
          module_id: string
          owner_id: string
          source_event_id: string
          source_event_type: string
          status: string
          tenant_id: string | null
          training_session_id: string | null
          twin_id: string
          updated_at: string
        }
        Insert: {
          confidence?: number | null
          created_at?: string
          id?: string
          intent_label?: string | null
          module_data?: Json
          module_id: string
          owner_id: string
          source_event_id: string
          source_event_type: string
          status?: string
          tenant_id?: string | null
          training_session_id?: string | null
          twin_id: string
          updated_at?: string
        }
        Update: {
          confidence?: number | null
          created_at?: string
          id?: string
          intent_label?: string | null
          module_data?: Json
          module_id?: string
          owner_id?: string
          source_event_id?: string
          source_event_type?: string
          status?: string
          tenant_id?: string | null
          training_session_id?: string | null
          twin_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "persona_modules_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_modules_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_modules_training_session_id_fkey"
            columns: ["training_session_id"]
            isOneToOne: false
            referencedRelation: "training_sessions"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_modules_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      persona_preferences: {
        Row: {
          candidate_a: Json
          candidate_b: Json
          clause_ids: string[]
          created_at: string
          id: string
          intent_label: string | null
          metadata: Json
          owner_id: string
          preferred: string
          prompt: string
          rationale: string | null
          tenant_id: string | null
          training_session_id: string
          twin_id: string
          updated_at: string
        }
        Insert: {
          candidate_a: Json
          candidate_b: Json
          clause_ids?: string[]
          created_at?: string
          id?: string
          intent_label?: string | null
          metadata?: Json
          owner_id: string
          preferred: string
          prompt: string
          rationale?: string | null
          tenant_id?: string | null
          training_session_id: string
          twin_id: string
          updated_at?: string
        }
        Update: {
          candidate_a?: Json
          candidate_b?: Json
          clause_ids?: string[]
          created_at?: string
          id?: string
          intent_label?: string | null
          metadata?: Json
          owner_id?: string
          preferred?: string
          prompt?: string
          rationale?: string | null
          tenant_id?: string | null
          training_session_id?: string
          twin_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "persona_preferences_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_preferences_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_preferences_training_session_id_fkey"
            columns: ["training_session_id"]
            isOneToOne: false
            referencedRelation: "training_sessions"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_preferences_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      persona_prompt_optimization_runs: {
        Row: {
          base_persona_spec_version: string | null
          best_objective_score: number | null
          best_variant_id: string | null
          candidate_count: number
          completed_at: string | null
          created_at: string
          created_by: string | null
          dataset_version: string | null
          id: string
          run_mode: string
          started_at: string
          status: string
          summary: Json
          tenant_id: string | null
          twin_id: string
          updated_at: string
        }
        Insert: {
          base_persona_spec_version?: string | null
          best_objective_score?: number | null
          best_variant_id?: string | null
          candidate_count?: number
          completed_at?: string | null
          created_at?: string
          created_by?: string | null
          dataset_version?: string | null
          id?: string
          run_mode: string
          started_at?: string
          status?: string
          summary?: Json
          tenant_id?: string | null
          twin_id: string
          updated_at?: string
        }
        Update: {
          base_persona_spec_version?: string | null
          best_objective_score?: number | null
          best_variant_id?: string | null
          candidate_count?: number
          completed_at?: string | null
          created_at?: string
          created_by?: string | null
          dataset_version?: string | null
          id?: string
          run_mode?: string
          started_at?: string
          status?: string
          summary?: Json
          tenant_id?: string | null
          twin_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "persona_prompt_optimization_runs_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_prompt_optimization_runs_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_prompt_optimization_runs_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      persona_prompt_variants: {
        Row: {
          activated_at: string | null
          created_at: string
          created_by: string | null
          id: string
          metrics: Json
          objective_score: number | null
          optimization_run_id: string | null
          render_options: Json
          source: string
          status: string
          tenant_id: string | null
          twin_id: string
          updated_at: string
          variant_id: string
        }
        Insert: {
          activated_at?: string | null
          created_at?: string
          created_by?: string | null
          id?: string
          metrics?: Json
          objective_score?: number | null
          optimization_run_id?: string | null
          render_options?: Json
          source?: string
          status?: string
          tenant_id?: string | null
          twin_id: string
          updated_at?: string
          variant_id: string
        }
        Update: {
          activated_at?: string | null
          created_at?: string
          created_by?: string | null
          id?: string
          metrics?: Json
          objective_score?: number | null
          optimization_run_id?: string | null
          render_options?: Json
          source?: string
          status?: string
          tenant_id?: string | null
          twin_id?: string
          updated_at?: string
          variant_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "persona_prompt_variants_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_prompt_variants_optimization_run_id_fkey"
            columns: ["optimization_run_id"]
            isOneToOne: false
            referencedRelation: "persona_prompt_optimization_runs"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_prompt_variants_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_prompt_variants_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      persona_specs: {
        Row: {
          created_at: string
          created_by: string | null
          id: string
          notes: string | null
          published_at: string | null
          source: string
          spec: Json
          status: string
          tenant_id: string | null
          twin_id: string
          updated_at: string
          version: string
        }
        Insert: {
          created_at?: string
          created_by?: string | null
          id?: string
          notes?: string | null
          published_at?: string | null
          source?: string
          spec: Json
          status?: string
          tenant_id?: string | null
          twin_id: string
          updated_at?: string
          version: string
        }
        Update: {
          created_at?: string
          created_by?: string | null
          id?: string
          notes?: string | null
          published_at?: string | null
          source?: string
          spec?: Json
          status?: string
          tenant_id?: string | null
          twin_id?: string
          updated_at?: string
          version?: string
        }
        Relationships: [
          {
            foreignKeyName: "persona_specs_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_specs_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_specs_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      persona_training_events: {
        Row: {
          conversation_id: string | null
          created_at: string
          created_by: string | null
          event_type: string
          id: string
          message_id: string | null
          payload: Json
          processed: boolean
          processed_at: string | null
          reason: string | null
          score: number | null
          source: string
          tenant_id: string | null
          trace_id: string | null
          twin_id: string
          updated_at: string
        }
        Insert: {
          conversation_id?: string | null
          created_at?: string
          created_by?: string | null
          event_type: string
          id?: string
          message_id?: string | null
          payload?: Json
          processed?: boolean
          processed_at?: string | null
          reason?: string | null
          score?: number | null
          source: string
          tenant_id?: string | null
          trace_id?: string | null
          twin_id: string
          updated_at?: string
        }
        Update: {
          conversation_id?: string | null
          created_at?: string
          created_by?: string | null
          event_type?: string
          id?: string
          message_id?: string | null
          payload?: Json
          processed?: boolean
          processed_at?: string | null
          reason?: string | null
          score?: number | null
          source?: string
          tenant_id?: string | null
          trace_id?: string | null
          twin_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "persona_training_events_conversation_id_fkey"
            columns: ["conversation_id"]
            isOneToOne: false
            referencedRelation: "conversations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_training_events_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_training_events_message_id_fkey"
            columns: ["message_id"]
            isOneToOne: false
            referencedRelation: "messages"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_training_events_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "persona_training_events_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      product_impressions: {
        Row: {
          clicked_at: string | null
          conversation_id: string | null
          id: string
          product_id: string | null
          shown_at: string | null
          viewer_fingerprint: string | null
        }
        Insert: {
          clicked_at?: string | null
          conversation_id?: string | null
          id?: string
          product_id?: string | null
          shown_at?: string | null
          viewer_fingerprint?: string | null
        }
        Update: {
          clicked_at?: string | null
          conversation_id?: string | null
          id?: string
          product_id?: string | null
          shown_at?: string | null
          viewer_fingerprint?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "product_impressions_conversation_id_fkey"
            columns: ["conversation_id"]
            isOneToOne: false
            referencedRelation: "conversations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "product_impressions_product_id_fkey"
            columns: ["product_id"]
            isOneToOne: false
            referencedRelation: "products"
            referencedColumns: ["id"]
          },
        ]
      }
      products: {
        Row: {
          active: boolean | null
          created_at: string | null
          description: string | null
          id: string
          image_url: string | null
          keywords: string[] | null
          priority: number | null
          product_link: string
          product_name: string
          promotion_frequency: string | null
          twin_id: string
        }
        Insert: {
          active?: boolean | null
          created_at?: string | null
          description?: string | null
          id?: string
          image_url?: string | null
          keywords?: string[] | null
          priority?: number | null
          product_link: string
          product_name: string
          promotion_frequency?: string | null
          twin_id: string
        }
        Update: {
          active?: boolean | null
          created_at?: string | null
          description?: string | null
          id?: string
          image_url?: string | null
          keywords?: string[] | null
          priority?: number | null
          product_link?: string
          product_name?: string
          promotion_frequency?: string | null
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "products_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      profile_versions: {
        Row: {
          approved_at: string | null
          approved_by: string | null
          created_at: string | null
          diff_json: Json | null
          edge_count: number
          id: string
          node_count: number
          notes: string | null
          snapshot_json: Json
          twin_id: string
          version: number
        }
        Insert: {
          approved_at?: string | null
          approved_by?: string | null
          created_at?: string | null
          diff_json?: Json | null
          edge_count?: number
          id?: string
          node_count?: number
          notes?: string | null
          snapshot_json: Json
          twin_id: string
          version: number
        }
        Update: {
          approved_at?: string | null
          approved_by?: string | null
          created_at?: string | null
          diff_json?: Json | null
          edge_count?: number
          id?: string
          node_count?: number
          notes?: string | null
          snapshot_json?: Json
          twin_id?: string
          version?: number
        }
        Relationships: [
          {
            foreignKeyName: "profile_versions_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      profiles: {
        Row: {
          areas_of_expertise: Json
          birth_year: number | null
          contributions: Json
          created_at: string
          death_year: number | null
          education: Json
          extra: Json
          featured_content: Json
          id: string
          image_url: string
          is_public: boolean
          key_achievements: Json
          linkedin_url: string | null
          name: string
          nationality: string
          occupation: string
          owner_id: string | null
          personality_traits: Json
          short_description: string
          slug: string | null
          social_links: Json
          speaking_style: string
          updated_at: string
          verified_profile: boolean
          work_experience: Json
        }
        Insert: {
          areas_of_expertise?: Json
          birth_year?: number | null
          contributions?: Json
          created_at?: string
          death_year?: number | null
          education?: Json
          extra?: Json
          featured_content?: Json
          id?: string
          image_url?: string
          is_public?: boolean
          key_achievements?: Json
          linkedin_url?: string | null
          name: string
          nationality?: string
          occupation: string
          owner_id?: string | null
          personality_traits?: Json
          short_description?: string
          slug?: string | null
          social_links?: Json
          speaking_style?: string
          updated_at?: string
          verified_profile?: boolean
          work_experience?: Json
        }
        Update: {
          areas_of_expertise?: Json
          birth_year?: number | null
          contributions?: Json
          created_at?: string
          death_year?: number | null
          education?: Json
          extra?: Json
          featured_content?: Json
          id?: string
          image_url?: string
          is_public?: boolean
          key_achievements?: Json
          linkedin_url?: string | null
          name?: string
          nationality?: string
          occupation?: string
          owner_id?: string | null
          personality_traits?: Json
          short_description?: string
          slug?: string | null
          social_links?: Json
          speaking_style?: string
          updated_at?: string
          verified_profile?: boolean
          work_experience?: Json
        }
        Relationships: []
      }
      queued_questions: {
        Row: {
          answered_at: string | null
          ask_count: number
          conversation_id: string | null
          created_at: string
          id: string
          owner_answer: string | null
          question: string
          status: string
          tenant_id: string | null
          topic: string
          twin_id: string
          updated_at: string
          visitor_user_id: string | null
        }
        Insert: {
          answered_at?: string | null
          ask_count?: number
          conversation_id?: string | null
          created_at?: string
          id?: string
          owner_answer?: string | null
          question: string
          status?: string
          tenant_id?: string | null
          topic: string
          twin_id: string
          updated_at?: string
          visitor_user_id?: string | null
        }
        Update: {
          answered_at?: string | null
          ask_count?: number
          conversation_id?: string | null
          created_at?: string
          id?: string
          owner_answer?: string | null
          question?: string
          status?: string
          tenant_id?: string | null
          topic?: string
          twin_id?: string
          updated_at?: string
          visitor_user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "queued_questions_conversation_id_fkey"
            columns: ["conversation_id"]
            isOneToOne: false
            referencedRelation: "adk_conversations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "queued_questions_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      sessions: {
        Row: {
          app_name: string
          create_time: string
          id: string
          state: Json
          update_time: string
          user_id: string
        }
        Insert: {
          app_name: string
          create_time: string
          id: string
          state: Json
          update_time: string
          user_id: string
        }
        Update: {
          app_name?: string
          create_time?: string
          id?: string
          state?: Json
          update_time?: string
          user_id?: string
        }
        Relationships: []
      }
      source_events: {
        Row: {
          correlation_id: string | null
          created_at: string
          ended_at: string | null
          error: Json | null
          id: string
          message: string | null
          metadata: Json | null
          provider: string
          source_id: string
          started_at: string
          status: string
          step: string
          twin_id: string
        }
        Insert: {
          correlation_id?: string | null
          created_at?: string
          ended_at?: string | null
          error?: Json | null
          id?: string
          message?: string | null
          metadata?: Json | null
          provider: string
          source_id: string
          started_at?: string
          status: string
          step: string
          twin_id: string
        }
        Update: {
          correlation_id?: string | null
          created_at?: string
          ended_at?: string | null
          error?: Json | null
          id?: string
          message?: string | null
          metadata?: Json | null
          provider?: string
          source_id?: string
          started_at?: string
          status?: string
          step?: string
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "source_events_source_id_fkey"
            columns: ["source_id"]
            isOneToOne: false
            referencedRelation: "sources"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "source_events_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      sources: {
        Row: {
          author: string | null
          chunk_count: number | null
          citation_url: string | null
          content_hash: string | null
          content_text: string | null
          created_at: string | null
          extracted_text_length: number | null
          file_size: number | null
          file_url: string | null
          filename: string
          health_status: string | null
          id: string
          is_verified_content: boolean
          keep_synced: boolean | null
          last_deep_scrub_at: string | null
          last_error: Json | null
          last_error_at: string | null
          last_event_at: string | null
          last_provider: string | null
          last_step: string | null
          publish_date: string | null
          status: string
          sync_config: Json | null
          twin_id: string
        }
        Insert: {
          author?: string | null
          chunk_count?: number | null
          citation_url?: string | null
          content_hash?: string | null
          content_text?: string | null
          created_at?: string | null
          extracted_text_length?: number | null
          file_size?: number | null
          file_url?: string | null
          filename: string
          health_status?: string | null
          id?: string
          is_verified_content?: boolean
          keep_synced?: boolean | null
          last_deep_scrub_at?: string | null
          last_error?: Json | null
          last_error_at?: string | null
          last_event_at?: string | null
          last_provider?: string | null
          last_step?: string | null
          publish_date?: string | null
          status?: string
          sync_config?: Json | null
          twin_id: string
        }
        Update: {
          author?: string | null
          chunk_count?: number | null
          citation_url?: string | null
          content_hash?: string | null
          content_text?: string | null
          created_at?: string | null
          extracted_text_length?: number | null
          file_size?: number | null
          file_url?: string | null
          filename?: string
          health_status?: string | null
          id?: string
          is_verified_content?: boolean
          keep_synced?: boolean | null
          last_deep_scrub_at?: string | null
          last_error?: Json | null
          last_error_at?: string | null
          last_event_at?: string | null
          last_provider?: string | null
          last_step?: string | null
          publish_date?: string | null
          status?: string
          sync_config?: Json | null
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "sources_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      tenant_api_keys: {
        Row: {
          allowed_domains: string[] | null
          allowed_twin_ids: string[] | null
          created_at: string | null
          created_by: string | null
          expires_at: string | null
          id: string
          is_active: boolean | null
          key_hash: string
          key_prefix: string
          last_used_at: string | null
          name: string
          scopes: string[] | null
          tenant_id: string
        }
        Insert: {
          allowed_domains?: string[] | null
          allowed_twin_ids?: string[] | null
          created_at?: string | null
          created_by?: string | null
          expires_at?: string | null
          id?: string
          is_active?: boolean | null
          key_hash: string
          key_prefix: string
          last_used_at?: string | null
          name: string
          scopes?: string[] | null
          tenant_id: string
        }
        Update: {
          allowed_domains?: string[] | null
          allowed_twin_ids?: string[] | null
          created_at?: string | null
          created_by?: string | null
          expires_at?: string | null
          id?: string
          is_active?: boolean | null
          key_hash?: string
          key_prefix?: string
          last_used_at?: string | null
          name?: string
          scopes?: string[] | null
          tenant_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "tenant_api_keys_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
        ]
      }
      tenants: {
        Row: {
          created_at: string | null
          id: string
          name: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          name: string
        }
        Update: {
          created_at?: string | null
          id?: string
          name?: string
        }
        Relationships: []
      }
      training_jobs: {
        Row: {
          completed_at: string | null
          created_at: string | null
          error_message: string | null
          id: string
          job_type: string
          metadata: Json | null
          priority: number
          source_id: string
          started_at: string | null
          status: string
          twin_id: string
          updated_at: string | null
        }
        Insert: {
          completed_at?: string | null
          created_at?: string | null
          error_message?: string | null
          id?: string
          job_type: string
          metadata?: Json | null
          priority?: number
          source_id: string
          started_at?: string | null
          status?: string
          twin_id: string
          updated_at?: string | null
        }
        Update: {
          completed_at?: string | null
          created_at?: string | null
          error_message?: string | null
          id?: string
          job_type?: string
          metadata?: Json | null
          priority?: number
          source_id?: string
          started_at?: string | null
          status?: string
          twin_id?: string
          updated_at?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "training_jobs_source_id_fkey"
            columns: ["source_id"]
            isOneToOne: false
            referencedRelation: "sources"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "training_jobs_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      training_sessions: {
        Row: {
          created_at: string
          ended_at: string | null
          id: string
          metadata: Json
          owner_id: string
          started_at: string
          status: string
          tenant_id: string | null
          twin_id: string
          updated_at: string
        }
        Insert: {
          created_at?: string
          ended_at?: string | null
          id?: string
          metadata?: Json
          owner_id: string
          started_at?: string
          status?: string
          tenant_id?: string | null
          twin_id: string
          updated_at?: string
        }
        Update: {
          created_at?: string
          ended_at?: string | null
          id?: string
          metadata?: Json
          owner_id?: string
          started_at?: string
          status?: string
          tenant_id?: string | null
          twin_id?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "training_sessions_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "training_sessions_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "training_sessions_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      twin_meeting_responses: {
        Row: {
          confidence: number
          created_at: string
          id: string
          is_deferral: boolean
          meeting_id: string
          question_text: string
          responded_at: string
          response_text: string
          sources: Json | null
          tenant_id: string
          twin_id: string
        }
        Insert: {
          confidence?: number
          created_at?: string
          id?: string
          is_deferral?: boolean
          meeting_id: string
          question_text: string
          responded_at?: string
          response_text: string
          sources?: Json | null
          tenant_id: string
          twin_id: string
        }
        Update: {
          confidence?: number
          created_at?: string
          id?: string
          is_deferral?: boolean
          meeting_id?: string
          question_text?: string
          responded_at?: string
          response_text?: string
          sources?: Json | null
          tenant_id?: string
          twin_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "twin_meeting_responses_meeting_id_fkey"
            columns: ["meeting_id"]
            isOneToOne: false
            referencedRelation: "meetings"
            referencedColumns: ["id"]
          },
        ]
      }
      twin_verification: {
        Row: {
          id: string
          metadata: Json | null
          requested_at: string | null
          status: string
          twin_id: string
          verification_method: string
          verified_at: string | null
          verified_by: string | null
        }
        Insert: {
          id?: string
          metadata?: Json | null
          requested_at?: string | null
          status?: string
          twin_id: string
          verification_method: string
          verified_at?: string | null
          verified_by?: string | null
        }
        Update: {
          id?: string
          metadata?: Json | null
          requested_at?: string | null
          status?: string
          twin_id?: string
          verification_method?: string
          verified_at?: string | null
          verified_by?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "twin_verification_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: true
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "twin_verification_verified_by_fkey"
            columns: ["verified_by"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
        ]
      }
      twins: {
        Row: {
          created_at: string | null
          creation_mode: string | null
          creator_id: string | null
          description: string | null
          id: string
          is_active: boolean
          is_verified: boolean
          name: string
          settings: Json | null
          specialization_id: string | null
          specialization_version: string | null
          status: string | null
          tenant_id: string
          updated_at: string | null
          verification_status: string | null
        }
        Insert: {
          created_at?: string | null
          creation_mode?: string | null
          creator_id?: string | null
          description?: string | null
          id?: string
          is_active?: boolean
          is_verified?: boolean
          name: string
          settings?: Json | null
          specialization_id?: string | null
          specialization_version?: string | null
          status?: string | null
          tenant_id: string
          updated_at?: string | null
          verification_status?: string | null
        }
        Update: {
          created_at?: string | null
          creation_mode?: string | null
          creator_id?: string | null
          description?: string | null
          id?: string
          is_active?: boolean
          is_verified?: boolean
          name?: string
          settings?: Json | null
          specialization_id?: string | null
          specialization_version?: string | null
          status?: string | null
          tenant_id?: string
          updated_at?: string | null
          verification_status?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "twins_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
        ]
      }
      user_states: {
        Row: {
          app_name: string
          state: Json
          update_time: string
          user_id: string
        }
        Insert: {
          app_name: string
          state: Json
          update_time: string
          user_id: string
        }
        Update: {
          app_name?: string
          state?: Json
          update_time?: string
          user_id?: string
        }
        Relationships: []
      }
      users: {
        Row: {
          avatar_url: string | null
          created_at: string | null
          email: string
          id: string
          last_active_at: string | null
          role: string
          tenant_id: string | null
        }
        Insert: {
          avatar_url?: string | null
          created_at?: string | null
          email: string
          id?: string
          last_active_at?: string | null
          role?: string
          tenant_id?: string | null
        }
        Update: {
          avatar_url?: string | null
          created_at?: string | null
          email?: string
          id?: string
          last_active_at?: string | null
          role?: string
          tenant_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "users_tenant_id_fkey"
            columns: ["tenant_id"]
            isOneToOne: false
            referencedRelation: "tenants"
            referencedColumns: ["id"]
          },
        ]
      }
      verified_qna: {
        Row: {
          answer: string
          created_at: string | null
          created_by: string | null
          id: string
          is_active: boolean
          question: string
          question_embedding: string | null
          twin_id: string
          updated_at: string | null
          visibility: string
        }
        Insert: {
          answer: string
          created_at?: string | null
          created_by?: string | null
          id?: string
          is_active?: boolean
          question: string
          question_embedding?: string | null
          twin_id: string
          updated_at?: string | null
          visibility?: string
        }
        Update: {
          answer?: string
          created_at?: string | null
          created_by?: string | null
          id?: string
          is_active?: boolean
          question?: string
          question_embedding?: string | null
          twin_id?: string
          updated_at?: string | null
          visibility?: string
        }
        Relationships: [
          {
            foreignKeyName: "verified_qna_created_by_fkey"
            columns: ["created_by"]
            isOneToOne: false
            referencedRelation: "users"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "verified_qna_twin_id_fkey"
            columns: ["twin_id"]
            isOneToOne: false
            referencedRelation: "twins"
            referencedColumns: ["id"]
          },
        ]
      }
      waitlist: {
        Row: {
          created_at: string
          email: string
          full_name: string
          id: string
          linkedin_url: string | null
          organization: string | null
          role: string | null
        }
        Insert: {
          created_at?: string
          email: string
          full_name: string
          id?: string
          linkedin_url?: string | null
          organization?: string | null
          role?: string | null
        }
        Update: {
          created_at?: string
          email?: string
          full_name?: string
          id?: string
          linkedin_url?: string | null
          organization?: string | null
          role?: string | null
        }
        Relationships: []
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      check_twin_tenant_access: {
        Args: { req_tenant_id: string; t_id: string }
        Returns: boolean
      }
      claim_graph_outbox_job: {
        Args: { p_job_id: string; p_now: string; p_worker_id: string }
        Returns: {
          attempt_count: number
          id: string
          operation: string
          payload: Json
          tenant_id: string
          twin_id: string
        }[]
      }
      cleanup_graph_outbox: {
        Args: { p_completed_before: string }
        Returns: number
      }
      create_edge_system: {
        Args: {
          e_desc: string
          e_props: Json
          e_type: string
          from_id: string
          t_id: string
          to_id: string
        }
        Returns: {
          created_at: string | null
          description: string | null
          from_node_id: string
          id: string
          properties: Json | null
          to_node_id: string
          twin_id: string
          type: string
          weight: number | null
        }[]
        SetofOptions: {
          from: "*"
          to: "edges"
          isOneToOne: false
          isSetofReturn: true
        }
      }
      create_memory_event_system: {
        Args: {
          p_event_type: string
          p_payload: Json
          p_source_id?: string
          p_source_type?: string
          p_status?: string
          p_tenant_id: string
          p_twin_id: string
        }
        Returns: {
          created_at: string | null
          event_type: string
          id: string
          payload: Json
          source_id: string | null
          source_type: string | null
          status: string
          tenant_id: string
          twin_id: string
        }[]
        SetofOptions: {
          from: "*"
          to: "memory_events"
          isOneToOne: false
          isSetofReturn: true
        }
      }
      create_node_system: {
        Args: {
          n_desc: string
          n_name: string
          n_props: Json
          n_type: string
          t_id: string
        }
        Returns: {
          created_at: string | null
          description: string | null
          id: string
          name: string
          properties: Json | null
          status: string | null
          twin_id: string
          type: string
          updated_at: string | null
        }[]
        SetofOptions: {
          from: "*"
          to: "nodes"
          isOneToOne: false
          isSetofReturn: true
        }
      }
      delete_all_versions_system: { Args: { t_id: string }; Returns: number }
      delete_profile_version_system: {
        Args: { t_id: string; ver: number }
        Returns: boolean
      }
      get_edges_system: {
        Args: { limit_val: number; t_id: string }
        Returns: {
          created_at: string | null
          description: string | null
          from_node_id: string
          id: string
          properties: Json | null
          to_node_id: string
          twin_id: string
          type: string
          weight: number | null
        }[]
        SetofOptions: {
          from: "*"
          to: "edges"
          isOneToOne: false
          isSetofReturn: true
        }
      }
      get_graph_outbox_depth: {
        Args: { p_tenant_id?: string }
        Returns: {
          count: number
          status: string
        }[]
      }
      get_latest_version_system: { Args: { t_id: string }; Returns: number }
      get_memory_events_system: {
        Args: { p_event_type?: string; p_limit?: number; p_twin_id: string }
        Returns: {
          created_at: string | null
          event_type: string
          id: string
          payload: Json
          source_id: string | null
          source_type: string | null
          status: string
          tenant_id: string
          twin_id: string
        }[]
        SetofOptions: {
          from: "*"
          to: "memory_events"
          isOneToOne: false
          isSetofReturn: true
        }
      }
      get_nodes_system: {
        Args: { limit_val: number; t_id: string }
        Returns: {
          created_at: string | null
          description: string | null
          id: string
          name: string
          properties: Json | null
          status: string | null
          twin_id: string
          type: string
          updated_at: string | null
        }[]
        SetofOptions: {
          from: "*"
          to: "nodes"
          isOneToOne: false
          isSetofReturn: true
        }
      }
      get_or_create_interview_session: {
        Args: { conv_id?: string; t_id: string }
        Returns: Json
      }
      get_profile_versions_system: {
        Args: { limit_val?: number; t_id: string }
        Returns: {
          approved_at: string | null
          approved_by: string | null
          created_at: string | null
          diff_json: Json | null
          edge_count: number
          id: string
          node_count: number
          notes: string | null
          snapshot_json: Json
          twin_id: string
          version: number
        }[]
        SetofOptions: {
          from: "*"
          to: "profile_versions"
          isOneToOne: false
          isSetofReturn: true
        }
      }
      get_twin_system: {
        Args: { t_id: string }
        Returns: {
          created_at: string | null
          creation_mode: string | null
          creator_id: string | null
          description: string | null
          id: string
          is_active: boolean
          is_verified: boolean
          name: string
          settings: Json | null
          specialization_id: string | null
          specialization_version: string | null
          status: string | null
          tenant_id: string
          updated_at: string | null
          verification_status: string | null
        }[]
        SetofOptions: {
          from: "*"
          to: "twins"
          isOneToOne: false
          isSetofReturn: true
        }
      }
      insert_profile_version_system: {
        Args: {
          approval_notes?: string
          approver?: string
          diff: Json
          e_count: number
          n_count: number
          snapshot: Json
          t_id: string
          ver: number
        }
        Returns: string
      }
      search_chunks: {
        Args: {
          allowed_tiers?: string[]
          match_count?: number
          min_similarity?: number
          query_embedding: string
          query_twin_id: string
        }
        Returns: {
          content: string
          id: string
          metadata: Json
          privacy_level: string
          similarity: number
          source_id: string
        }[]
      }
      search_chunks_global: {
        Args: {
          allowed_tiers?: string[]
          global_limit?: number
          per_tenant_limit?: number
          query_embedding: string
          tenant_ids: string[]
        }
        Returns: {
          chunk_id: string
          content: string
          metadata: Json
          similarity: number
          twin_id: string
        }[]
      }
      search_meeting_chunks: {
        Args: { p_top_k?: number; p_twin_id: string; query_embedding: string }
        Returns: {
          content: string
          id: string
          metadata: Json
          similarity: number
        }[]
      }
      update_interview_session:
        | {
            Args: {
              add_template_id?: string
              increment_turn?: boolean
              new_blueprint?: Json
              new_intent_confirmed?: boolean
              new_intent_summary?: string
              new_slots_filled?: number
              new_stage?: string
              new_total_slots?: number
              session_id: string
            }
            Returns: Json
          }
        | {
            Args: {
              add_skipped_slot?: string
              add_template_id?: string
              append_quality_score?: Json
              increment_turn?: boolean
              new_blueprint?: Json
              new_clarification_attempts?: number
              new_current_question_id?: string
              new_intent_confirmed?: boolean
              new_intent_summary?: string
              new_last_repair_strategy?: string
              new_slots_filled?: number
              new_stage?: string
              new_total_slots?: number
              reset_clarification_attempts?: boolean
              session_id: string
            }
            Returns: Json
          }
      update_memory_event_system: {
        Args: { p_event_id: string; p_payload: Json }
        Returns: {
          created_at: string | null
          event_type: string
          id: string
          payload: Json
          source_id: string | null
          source_type: string | null
          status: string
          tenant_id: string
          twin_id: string
        }[]
        SetofOptions: {
          from: "*"
          to: "memory_events"
          isOneToOne: false
          isSetofReturn: true
        }
      }
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const
