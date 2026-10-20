# Sample Multi-Product PRD

A tiny PRD for Buildshift plan / multi-role smoke tests.

## Identity Platform

Shared auth and session handling for all products.

### Requirements

1. Users can sign up with email and password
2. Sessions expire after 7 days of inactivity
3. API keys can be issued for service accounts

## Demo Notes App

A minimal notes product that depends on identity.

### Requirements

1. Authenticated users can create a note with a title and body
2. Users can list their own notes
3. Notes support markdown rendering on read

## Design System

Shared UI primitives used by Demo Notes and future apps.

### Requirements

1. Provide a primary button component with loading state
2. Provide a text input with label and error message
3. Document spacing tokens in a styleguide markdown file
