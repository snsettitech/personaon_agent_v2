-- =====================================================
-- Products (Phase 7 - Digital Brains)
-- =====================================================
-- Products that can be promoted in chat when keywords match.
-- product_impressions tracks shown/clicked for frequency caps.
-- =====================================================

CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    image_url TEXT,
    product_name TEXT NOT NULL,
    product_link TEXT NOT NULL,
    description TEXT,
    keywords TEXT[],
    promotion_frequency TEXT CHECK (promotion_frequency IN ('every_mention', 'once_per_user', 'once_per_conversation')) DEFAULT 'once_per_conversation',
    priority INT DEFAULT 0,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS product_impressions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id UUID REFERENCES products(id) ON DELETE CASCADE,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    viewer_fingerprint TEXT,
    shown_at TIMESTAMPTZ DEFAULT NOW(),
    clicked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_products_twin_id ON products(twin_id);
CREATE INDEX IF NOT EXISTS idx_product_impressions_product_id ON product_impressions(product_id);
CREATE INDEX IF NOT EXISTS idx_product_impressions_conversation_id ON product_impressions(conversation_id);

-- RLS: products follow twin ownership
ALTER TABLE products ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS products_select_tenant ON products;
CREATE POLICY products_select_tenant ON products
    FOR SELECT USING (
        twin_id IN (SELECT id FROM twins WHERE tenant_id = (SELECT tenant_id FROM users WHERE id = auth.uid()))
    );

DROP POLICY IF EXISTS products_insert_tenant ON products;
CREATE POLICY products_insert_tenant ON products
    FOR INSERT WITH CHECK (
        twin_id IN (SELECT id FROM twins WHERE tenant_id = (SELECT tenant_id FROM users WHERE id = auth.uid()))
    );

DROP POLICY IF EXISTS products_update_tenant ON products;
CREATE POLICY products_update_tenant ON products
    FOR UPDATE USING (
        twin_id IN (SELECT id FROM twins WHERE tenant_id = (SELECT tenant_id FROM users WHERE id = auth.uid()))
    );

DROP POLICY IF EXISTS products_delete_tenant ON products;
CREATE POLICY products_delete_tenant ON products
    FOR DELETE USING (
        twin_id IN (SELECT id FROM twins WHERE tenant_id = (SELECT tenant_id FROM users WHERE id = auth.uid()))
    );

-- product_impressions: readable by tenant
ALTER TABLE product_impressions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS product_impressions_select_tenant ON product_impressions;
CREATE POLICY product_impressions_select_tenant ON product_impressions
    FOR SELECT USING (
        product_id IN (
            SELECT p.id FROM products p
            JOIN twins t ON p.twin_id = t.id
            WHERE t.tenant_id = (SELECT tenant_id FROM users WHERE id = auth.uid())
        )
    );

DROP POLICY IF EXISTS product_impressions_insert_tenant ON product_impressions;
CREATE POLICY product_impressions_insert_tenant ON product_impressions
    FOR INSERT WITH CHECK (
        product_id IN (
            SELECT p.id FROM products p
            JOIN twins t ON p.twin_id = t.id
            WHERE t.tenant_id = (SELECT tenant_id FROM users WHERE id = auth.uid())
        )
    );
