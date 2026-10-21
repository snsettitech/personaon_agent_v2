'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardContent, useToast } from '@/components/ui';
import { useTwin } from '@/lib/context/TwinContext';
import { authFetchStandalone } from '@/lib/hooks/useAuthFetch';
import { resolveApiBaseUrl } from '@/lib/api';
import { API_ENDPOINTS } from '@/lib/constants';

interface Product {
  id: string;
  twin_id: string;
  product_name: string;
  product_link: string;
  image_url?: string | null;
  description?: string | null;
  keywords?: string[];
  promotion_frequency: string;
  priority: number;
  active: boolean;
  created_at: string;
}

type PromotionFrequency = 'every_mention' | 'once_per_user' | 'once_per_conversation';

interface ProductFormState {
  product_name: string;
  product_link: string;
  image_url: string;
  description: string;
  keywords: string;
  promotion_frequency: PromotionFrequency;
  priority: number;
  active: boolean;
}

const BASE_URL = resolveApiBaseUrl();

export default function ProductsPage() {
  const { showToast } = useToast();
  const { activeTwin, isLoading: twinLoading } = useTwin();
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<ProductFormState>({
    product_name: '',
    product_link: '',
    image_url: '',
    description: '',
    keywords: '',
    promotion_frequency: 'once_per_conversation',
    priority: 0,
    active: true,
  });

  const twinId = activeTwin?.id;

  const fetchProducts = useCallback(async () => {
    if (!twinId) return;
    try {
      const res = await authFetchStandalone(`${BASE_URL}${API_ENDPOINTS.PRODUCTS(twinId)}?active_only=false`);
      if (res.ok) {
        const data = await res.json();
        setProducts(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error(err);
      showToast?.('Failed to load products', 'error');
    } finally {
      setLoading(false);
    }
  }, [twinId, showToast]);

  useEffect(() => {
    if (twinId) {
      fetchProducts();
    } else if (!twinLoading) {
      setLoading(false);
    }
  }, [twinId, twinLoading, fetchProducts]);

  const resetForm = () => {
    setForm({
      product_name: '',
      product_link: '',
      image_url: '',
      description: '',
      keywords: '',
      promotion_frequency: 'once_per_conversation',
      priority: 0,
      active: true,
    });
    setEditingId(null);
    setShowForm(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!twinId) return;
    const keywords = form.keywords
      .split(/[,\s]+/)
      .map((k) => k.trim())
      .filter(Boolean);
    const payload = {
      product_name: form.product_name,
      product_link: form.product_link,
      image_url: form.image_url || undefined,
      description: form.description || undefined,
      keywords,
      promotion_frequency: form.promotion_frequency,
      priority: form.priority,
      active: form.active,
    };

    try {
      if (editingId) {
        const res = await authFetchStandalone(`${BASE_URL}${API_ENDPOINTS.PRODUCT_UPDATE(editingId)}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error('Update failed');
        showToast?.('Product updated', 'success');
      } else {
        const res = await authFetchStandalone(`${BASE_URL}${API_ENDPOINTS.PRODUCTS(twinId)}`, {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error('Create failed');
        showToast?.('Product created', 'success');
      }
      resetForm();
      await fetchProducts();
    } catch (err) {
      console.error(err);
      showToast?.('Failed to save product', 'error');
    }
  };

  const handleEdit = (p: Product) => {
    setForm({
      product_name: p.product_name,
      product_link: p.product_link,
      image_url: p.image_url || '',
      description: p.description || '',
      keywords: (p.keywords || []).join(', '),
      promotion_frequency: p.promotion_frequency as PromotionFrequency,
      priority: p.priority,
      active: p.active,
    });
    setEditingId(p.id);
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this product?')) return;
    try {
      const res = await authFetchStandalone(`${BASE_URL}${API_ENDPOINTS.PRODUCT_DELETE(id)}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('Delete failed');
      showToast?.('Product deleted', 'success');
      await fetchProducts();
      if (editingId === id) resetForm();
    } catch (err) {
      console.error(err);
      showToast?.('Failed to delete product', 'error');
    }
  };

  const freqLabel = (f: string) => {
    switch (f) {
      case 'every_mention':
        return 'Every mention';
      case 'once_per_user':
        return 'Once per user';
      default:
        return 'Once per conversation';
    }
  };

  if (twinLoading) {
    return (
      <div className="flex justify-center p-20">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600" />
      </div>
    );
  }

  if (!twinId) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center max-w-md p-8">
          <div className="w-16 h-16 bg-blue-900/50 rounded-2xl flex items-center justify-center mx-auto mb-6">
            <svg className="w-8 h-8 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z" />
            </svg>
          </div>
          <h2 className="text-2xl font-bold text-white mb-3">No persona found</h2>
          <p className="text-slate-400 mb-6">Create your persona first to manage products.</p>
          <a href="/dashboard" className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-xl font-semibold hover:bg-blue-700 transition-colors">
            Go to Dashboard
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-8 pb-20">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-4xl font-black tracking-tight text-white mb-2">Products</h1>
          <p className="text-slate-400 font-medium">Promote products in chat when keywords match.</p>
        </div>
        <button
          onClick={() => {
            resetForm();
            setShowForm(true);
          }}
          className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-bold transition-all"
        >
          + Add Product
        </button>
      </div>

      {showForm && (
        <Card glass>
          <CardHeader className="flex flex-row items-center justify-between border-b border-white/5">
            <h3 className="text-lg font-bold text-white">{editingId ? 'Edit Product' : 'Add Product'}</h3>
            <button onClick={resetForm} className="text-slate-400 hover:text-white text-sm">
              Cancel
            </button>
          </CardHeader>
          <CardContent className="p-6">
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-1">Product Name</label>
                  <input
                    type="text"
                    value={form.product_name}
                    onChange={(e) => setForm({ ...form, product_name: e.target.value })}
                    required
                    className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g. My Book"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-1">Product Link</label>
                  <input
                    type="url"
                    value={form.product_link}
                    onChange={(e) => setForm({ ...form, product_link: e.target.value })}
                    required
                    className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="https://..."
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1">Image URL (optional)</label>
                <input
                  type="url"
                  value={form.image_url}
                  onChange={(e) => setForm({ ...form, image_url: e.target.value })}
                  className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="https://..."
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1">Description (optional)</label>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  rows={2}
                  className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Brief description"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1">Keywords (comma-separated)</label>
                <input
                  type="text"
                  value={form.keywords}
                  onChange={(e) => setForm({ ...form, keywords: e.target.value })}
                  className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="book, guide, course"
                />
              </div>
              <div className="flex flex-wrap gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-1">Promotion Frequency</label>
                  <select
                    value={form.promotion_frequency}
                    onChange={(e) => setForm({ ...form, promotion_frequency: e.target.value as any })}
                    className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="once_per_conversation">Once per conversation</option>
                    <option value="once_per_user">Once per user</option>
                    <option value="every_mention">Every mention</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-1">Priority</label>
                  <input
                    type="number"
                    min={0}
                    value={form.priority}
                    onChange={(e) => setForm({ ...form, priority: parseInt(e.target.value) || 0 })}
                    className="w-24 px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div className="flex items-center gap-2 pt-6">
                  <input
                    type="checkbox"
                    id="active"
                    checked={form.active}
                    onChange={(e) => setForm({ ...form, active: e.target.checked })}
                    className="rounded border-white/20"
                  />
                  <label htmlFor="active" className="text-sm text-slate-300">Active</label>
                </div>
              </div>
              <div className="pt-4">
                <button
                  type="submit"
                  className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-bold transition-all"
                >
                  {editingId ? 'Update' : 'Create'} Product
                </button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      <Card glass>
        <CardHeader className="border-b border-white/5">
          <h3 className="text-lg font-bold text-white">Your Products</h3>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-10 text-center text-slate-400">Loading...</div>
          ) : products.length === 0 ? (
            <div className="p-10 text-center">
              <div className="text-4xl mb-3">📦</div>
              <p className="text-slate-500 font-medium">No products yet</p>
              <p className="text-slate-600 text-sm mt-1">Add products to promote your offerings in chat.</p>
              <button
                onClick={() => setShowForm(true)}
                className="mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium"
              >
                Add Product
              </button>
            </div>
          ) : (
            <div className="divide-y divide-white/5">
              {products.map((p) => (
                <div key={p.id} className="p-4 hover:bg-white/5 transition-colors flex items-center justify-between gap-4">
                  <div className="flex items-center gap-4 min-w-0">
                    {p.image_url ? (
                      <img src={p.image_url} alt="" className="w-12 h-12 rounded-lg object-cover shrink-0" />
                    ) : (
                      <div className="w-12 h-12 rounded-lg bg-white/10 flex items-center justify-center shrink-0">
                        <span className="text-xl">📦</span>
                      </div>
                    )}
                    <div className="min-w-0">
                      <a
                        href={p.product_link}
                        target="_blank"
                        rel="noreferrer"
                        className="font-semibold text-white hover:text-blue-300 truncate block"
                      >
                        {p.product_name}
                      </a>
                      <p className="text-slate-500 text-sm truncate">{p.product_link}</p>
                      <div className="flex flex-wrap gap-2 mt-1">
                        {p.keywords?.map((k) => (
                          <span key={k} className="px-2 py-0.5 bg-white/10 text-slate-400 text-xs rounded">
                            {k}
                          </span>
                        ))}
                        <span className="px-2 py-0.5 bg-blue-500/20 text-blue-300 text-xs rounded">
                          {freqLabel(p.promotion_frequency)}
                        </span>
                        {!p.active && (
                          <span className="px-2 py-0.5 bg-slate-500/20 text-slate-400 text-xs rounded">Inactive</span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={() => handleEdit(p)}
                      className="px-3 py-1.5 text-xs bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-slate-200"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(p.id)}
                      className="px-3 py-1.5 text-xs bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/30 rounded-lg"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
