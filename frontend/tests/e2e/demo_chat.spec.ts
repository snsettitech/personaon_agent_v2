import { expect, test } from '@playwright/test';

test('landing demo chat reuses conversation_id across turns', async ({ page }) => {
  const requestBodies: Array<Record<string, unknown>> = [];

  await page.addInitScript(() => {
    window.localStorage.clear();
  });

  await page.route('**/v2/chat/public/demo-twin/demo-token', async (route) => {
    const body = (route.request().postDataJSON() as Record<string, unknown>) || {};
    requestBodies.push(body);

    const conversationId =
      typeof body.conversation_id === 'string' ? body.conversation_id : 'conv-demo-1';

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        conversation_id: conversationId,
        message: `Reply ${requestBodies.length}`,
      }),
    });
  });

  await page.goto('/');

  const input = page.getByPlaceholder('Ask Alex anything...');
  const sendButton = page.getByRole('button', { name: 'Send message' });

  await expect(input).toBeVisible();

  await input.fill('First question');
  await sendButton.click();
  await expect(page.getByText('Reply 1')).toBeVisible();

  await input.fill('Second question');
  await sendButton.click();
  await expect(page.getByText('Reply 2')).toBeVisible();

  expect(requestBodies).toHaveLength(2);
  expect(requestBodies[0]).toMatchObject({
    message: 'First question',
    conversation_id: null,
  });
  expect(requestBodies[1]).toMatchObject({
    message: 'Second question',
    conversation_id: 'conv-demo-1',
  });
});
