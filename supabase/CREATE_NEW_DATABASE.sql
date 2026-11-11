-- IMPORTANT: this bootstrap is for a NEW, EMPTY Pharmacy360 database only.
-- Supabase supplies auth.users and PostgreSQL automatically.
-- This schema uses SUPABASE AUTH for passwords, sessions, email verification and invites.
-- Public user profiles reference auth.users(id), not custom password tables.
-- This script NEVER deletes existing data, tables, or accounts.
BEGIN;
SET LOCAL search_path TO public;

DO $fresh_install$
DECLARE
  already_present text;
BEGIN
  SELECT string_agg(table_name, ', ' ORDER BY table_name)
    INTO already_present
  FROM unnest(ARRAY[
      'profiles',
      'branches',
      'categories',
      'manufacturers',
      'suppliers',
      'products',
      'branch_inventory',
      'stock_receipts',
      'product_batches',
      'stock_movements',
      'promotions',
      'promotion_products',
      'favorites',
      'customer_addresses',
      'prescriptions',
      'consultations',
      'consultation_messages',
      'orders',
      'order_items',
      'payments',
      'deliveries',
      'order_status_history',
      'operating_expenses',
      'payroll_entries',
      'staff_tasks',
      'attendance_records',
      'staff_reports',
      'activity_logs',
      'stock_deliveries',
      'stock_delivery_items'
  ]::text[]) AS existing(table_name)
  WHERE to_regclass(format('public.%I', table_name)) IS NOT NULL;

  IF already_present IS NOT NULL THEN
    RAISE EXCEPTION 'Fresh installation stopped: Pharmacy360 table(s) already exist: %. No data was deleted.', already_present;
  END IF;
END
$fresh_install$;






CREATE TABLE public.profiles (
  id UUID PRIMARY KEY,
  username VARCHAR(60) NULL UNIQUE,
  staff_id VARCHAR(32) NULL UNIQUE,
  full_name VARCHAR(160) NOT NULL DEFAULT '',
  email VARCHAR(255) NULL,
  phone VARCHAR(32) NULL,
  role TEXT CHECK (role IN ('customer','admin','pharmacist','merchandiser','delivery')) NOT NULL DEFAULT 'customer',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_profile_identity FOREIGN KEY(id) REFERENCES auth.users(id) ON DELETE CASCADE
);

CREATE TABLE public.branches (
  id UUID PRIMARY KEY,
  name VARCHAR(160) NOT NULL,
  address_line VARCHAR(255) NOT NULL,
  barangay VARCHAR(120) NULL,
  city VARCHAR(120) NOT NULL,
  province VARCHAR(120) NULL,
  postal_code VARCHAR(20) NULL,
  phone VARCHAR(32) NULL,
  latitude DECIMAL(10,7) NULL,
  longitude DECIMAL(10,7) NULL,
  pickup_instructions TEXT NULL,
  is_pickup_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  is_delivery_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.categories (
  id UUID PRIMARY KEY,
  name VARCHAR(120) NOT NULL UNIQUE,
  slug VARCHAR(120) NOT NULL UNIQUE,
  icon VARCHAR(80) NULL,
  sort_order INT NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.manufacturers (
  id UUID PRIMARY KEY,
  name VARCHAR(180) NOT NULL UNIQUE,
  logo_url TEXT NULL,
  website_url TEXT NULL,
  is_partner BOOLEAN NOT NULL DEFAULT FALSE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.suppliers (
  id UUID PRIMARY KEY,
  name VARCHAR(180) NOT NULL UNIQUE,
  contact_name VARCHAR(160) NULL,
  email VARCHAR(255) NULL,
  phone VARCHAR(32) NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.products (
  id UUID PRIMARY KEY,
  sku VARCHAR(64) NULL UNIQUE,
  category_id UUID NULL,
  manufacturer_id UUID NULL,
  name VARCHAR(180) NOT NULL,
  generic_name VARCHAR(180) NULL,
  brand VARCHAR(180) NULL,
  dosage_form VARCHAR(80) NULL,
  strength VARCHAR(80) NULL,
  short_use VARCHAR(255) NULL,
  description TEXT NULL,
  selling_price DECIMAL(12,2) NOT NULL DEFAULT 0,
  requires_prescription BOOLEAN NOT NULL DEFAULT FALSE,
  image_url TEXT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_by UUID NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_product_category FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE SET NULL,
  CONSTRAINT fk_product_manufacturer FOREIGN KEY(manufacturer_id) REFERENCES manufacturers(id) ON DELETE SET NULL,
  CONSTRAINT fk_product_creator FOREIGN KEY(created_by) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.branch_inventory (
  branch_id UUID NOT NULL,
  product_id UUID NOT NULL,
  on_hand INT NOT NULL DEFAULT 0,
  reserved INT NOT NULL DEFAULT 0,
  reorder_level INT NOT NULL DEFAULT 10,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(branch_id,product_id),
  CONSTRAINT fk_inventory_branch FOREIGN KEY(branch_id) REFERENCES branches(id) ON DELETE CASCADE,
  CONSTRAINT fk_inventory_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE public.stock_receipts (
  id UUID PRIMARY KEY,
  branch_id UUID NOT NULL,
  supplier_id UUID NULL,
  delivery_reference VARCHAR(120) NULL,
  delivery_date DATE NOT NULL,
  received_by UUID NULL,
  notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_receipt_branch FOREIGN KEY(branch_id) REFERENCES branches(id),
  CONSTRAINT fk_receipt_supplier FOREIGN KEY(supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL,
  CONSTRAINT fk_receipt_staff FOREIGN KEY(received_by) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.product_batches (
  id UUID PRIMARY KEY,
  receipt_id UUID NULL,
  branch_id UUID NOT NULL,
  product_id UUID NOT NULL,
  manufacturer_id UUID NULL,
  batch_number VARCHAR(100) NULL,
  delivery_date DATE NOT NULL,
  expiration_date DATE NULL,
  quantity_received INT NOT NULL,
  quantity_remaining INT NOT NULL,
  cost_per_unit DECIMAL(12,2) NOT NULL DEFAULT 0,
  received_by UUID NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_batch_receipt FOREIGN KEY(receipt_id) REFERENCES stock_receipts(id) ON DELETE SET NULL,
  CONSTRAINT fk_batch_branch FOREIGN KEY(branch_id) REFERENCES branches(id) ON DELETE CASCADE,
  CONSTRAINT fk_batch_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
  CONSTRAINT fk_batch_manufacturer FOREIGN KEY(manufacturer_id) REFERENCES manufacturers(id) ON DELETE SET NULL,
  CONSTRAINT fk_batch_staff FOREIGN KEY(received_by) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.stock_movements (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  branch_id UUID NOT NULL,
  product_id UUID NOT NULL,
  batch_id UUID NULL,
  movement_type TEXT CHECK (movement_type IN ('receive','sale','adjustment','return','expired','damaged','cancel_restore')) NOT NULL,
  quantity INT NOT NULL,
  reference_type VARCHAR(60) NULL,
  reference_id UUID NULL,
  note TEXT NULL,
  actor_id UUID NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_move_branch FOREIGN KEY(branch_id) REFERENCES branches(id) ON DELETE CASCADE,
  CONSTRAINT fk_move_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
  CONSTRAINT fk_move_batch FOREIGN KEY(batch_id) REFERENCES product_batches(id) ON DELETE SET NULL,
  CONSTRAINT fk_move_actor FOREIGN KEY(actor_id) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.promotions (
  id UUID PRIMARY KEY,
  kind TEXT CHECK (kind IN ('hot_deal','sale','promo')) NOT NULL,
  title VARCHAR(180) NOT NULL,
  subtitle TEXT NULL,
  banner_image_url TEXT NULL,
  discount_type TEXT CHECK (discount_type IN ('percentage','fixed')) NOT NULL DEFAULT 'percentage',
  discount_value DECIMAL(12,2) NOT NULL DEFAULT 0,
  starts_at TIMESTAMPTZ NULL,
  ends_at TIMESTAMPTZ NULL,
  priority INT NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_by UUID NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_promo_creator FOREIGN KEY(created_by) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.promotion_products (
  promotion_id UUID NOT NULL,
  product_id UUID NOT NULL,
  PRIMARY KEY(promotion_id,product_id),
  CONSTRAINT fk_pp_promo FOREIGN KEY(promotion_id) REFERENCES promotions(id) ON DELETE CASCADE,
  CONSTRAINT fk_pp_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE public.favorites (
  user_id UUID NOT NULL,
  product_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(user_id,product_id),
  CONSTRAINT fk_favorite_user FOREIGN KEY(user_id) REFERENCES profiles(id) ON DELETE CASCADE,
  CONSTRAINT fk_favorite_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE public.customer_addresses (
  id UUID PRIMARY KEY,
  customer_id UUID NOT NULL,
  label VARCHAR(40) NOT NULL DEFAULT 'Home',
  recipient_name VARCHAR(160) NOT NULL,
  recipient_phone VARCHAR(32) NOT NULL,
  province VARCHAR(120) NOT NULL,
  city VARCHAR(120) NOT NULL,
  barangay VARCHAR(120) NOT NULL,
  postal_code VARCHAR(20) NULL,
  street_address VARCHAR(255) NOT NULL,
  landmark VARCHAR(255) NULL,
  latitude DECIMAL(10,7) NULL,
  longitude DECIMAL(10,7) NULL,
  is_default BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_address_customer FOREIGN KEY(customer_id) REFERENCES profiles(id) ON DELETE CASCADE
);

CREATE TABLE public.prescriptions (
  id UUID PRIMARY KEY,
  customer_id UUID NOT NULL,
  product_id UUID NULL,
  storage_path TEXT NOT NULL,
  original_filename VARCHAR(255) NULL,
  status TEXT CHECK (status IN ('pending','needs_information','approved','rejected','expired')) NOT NULL DEFAULT 'pending',
  pharmacist_id UUID NULL,
  pharmacist_note TEXT NULL,
  reviewed_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_rx_customer FOREIGN KEY(customer_id) REFERENCES profiles(id) ON DELETE CASCADE,
  CONSTRAINT fk_rx_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL,
  CONSTRAINT fk_rx_pharmacist FOREIGN KEY(pharmacist_id) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.consultations (
  id UUID PRIMARY KEY,
  customer_id UUID NOT NULL,
  product_id UUID NULL,
  prescription_id UUID NULL,
  subject VARCHAR(220) NOT NULL,
  status TEXT CHECK (status IN ('open','waiting_customer','waiting_pharmacist','resolved','closed')) NOT NULL DEFAULT 'open',
  assigned_pharmacist_id UUID NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_consult_customer FOREIGN KEY(customer_id) REFERENCES profiles(id) ON DELETE CASCADE,
  CONSTRAINT fk_consult_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL,
  CONSTRAINT fk_consult_rx FOREIGN KEY(prescription_id) REFERENCES prescriptions(id) ON DELETE SET NULL,
  CONSTRAINT fk_consult_pharm FOREIGN KEY(assigned_pharmacist_id) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.consultation_messages (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  consultation_id UUID NOT NULL,
  sender_id UUID NULL,
  sender_role TEXT CHECK (sender_role IN ('customer','admin','pharmacist','merchandiser','delivery')) NOT NULL,
  message TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_msg_consult FOREIGN KEY(consultation_id) REFERENCES consultations(id) ON DELETE CASCADE,
  CONSTRAINT fk_msg_sender FOREIGN KEY(sender_id) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.orders (
  id UUID PRIMARY KEY,
  order_number VARCHAR(80) NOT NULL UNIQUE,
  customer_id UUID NOT NULL,
  branch_id UUID NOT NULL,
  address_id UUID NULL,
  fulfillment TEXT CHECK (fulfillment IN ('pickup','delivery')) NOT NULL,
  status TEXT CHECK (status IN ('placed','confirmed','awaiting_prescription','preparing','packed','ready_for_pickup','handed_to_courier','in_transit','out_for_delivery','delivered','picked_up','order_received','completed','cancelled')) NOT NULL DEFAULT 'placed',
  subtotal DECIMAL(12,2) NOT NULL DEFAULT 0,
  discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  delivery_fee DECIMAL(12,2) NOT NULL DEFAULT 0,
  total_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  payment_method VARCHAR(60) NOT NULL,
  payment_status TEXT CHECK (payment_status IN ('unpaid','pending','paid','failed','refunded')) NOT NULL DEFAULT 'unpaid',
  notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_order_customer FOREIGN KEY(customer_id) REFERENCES profiles(id),
  CONSTRAINT fk_order_branch FOREIGN KEY(branch_id) REFERENCES branches(id),
  CONSTRAINT fk_order_address FOREIGN KEY(address_id) REFERENCES customer_addresses(id) ON DELETE SET NULL
);

CREATE TABLE public.order_items (
  id UUID PRIMARY KEY,
  order_id UUID NOT NULL,
  product_id UUID NULL,
  prescription_id UUID NULL,
  product_name_snapshot VARCHAR(180) NOT NULL,
  unit_price DECIMAL(12,2) NOT NULL,
  final_unit_price DECIMAL(12,2) NOT NULL,
  unit_cost_snapshot DECIMAL(12,2) NOT NULL DEFAULT 0,
  quantity INT NOT NULL,
  line_discount DECIMAL(12,2) NOT NULL DEFAULT 0,
  line_total DECIMAL(12,2) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_item_order FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
  CONSTRAINT fk_item_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL,
  CONSTRAINT fk_item_rx FOREIGN KEY(prescription_id) REFERENCES prescriptions(id) ON DELETE SET NULL
);

CREATE TABLE public.payments (
  id UUID PRIMARY KEY,
  order_id UUID NOT NULL,
  provider VARCHAR(100) NULL,
  external_payment_reference VARCHAR(180) NULL,
  method VARCHAR(60) NOT NULL,
  status TEXT CHECK (status IN ('unpaid','pending','paid','failed','refunded')) NOT NULL DEFAULT 'unpaid',
  amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  paid_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_payment_order FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
);

CREATE TABLE public.deliveries (
  id UUID PRIMARY KEY,
  order_id UUID NOT NULL UNIQUE,
  provider VARCHAR(100) NULL,
  external_delivery_reference VARCHAR(180) NULL,
  tracking_url TEXT NULL,
  status TEXT CHECK (status IN ('not_requested','queued','assigned','picked_up','in_transit','out_for_delivery','delivered','failed','cancelled')) NOT NULL DEFAULT 'queued',
  rider_reference VARCHAR(160) NULL,
  assigned_to UUID NULL,
  payment_sent_at TIMESTAMPTZ NULL,
  last_latitude DECIMAL(10,7) NULL,
  last_longitude DECIMAL(10,7) NULL,
  last_location_at TIMESTAMPTZ NULL,
  estimated_delivery_at TIMESTAMPTZ NULL,
  picked_up_at TIMESTAMPTZ NULL,
  delivered_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_delivery_order FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
  CONSTRAINT fk_delivery_assignee FOREIGN KEY(assigned_to) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.order_status_history (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  order_id UUID NOT NULL,
  status TEXT CHECK (status IN ('placed','confirmed','awaiting_prescription','preparing','packed','ready_for_pickup','handed_to_courier','in_transit','out_for_delivery','delivered','picked_up','order_received','completed','cancelled')) NOT NULL,
  note TEXT NULL,
  actor_id UUID NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_history_order FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
  CONSTRAINT fk_history_actor FOREIGN KEY(actor_id) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.operating_expenses (
  id UUID PRIMARY KEY,
  expense_date DATE NOT NULL,
  category VARCHAR(100) NOT NULL,
  description VARCHAR(255) NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  recorded_by UUID NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_expense_admin FOREIGN KEY(recorded_by) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.payroll_entries (
  id UUID PRIMARY KEY,
  employee_id UUID NOT NULL,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  gross_wage DECIMAL(12,2) NOT NULL,
  deductions DECIMAL(12,2) NOT NULL DEFAULT 0,
  net_amount DECIMAL(12,2) NOT NULL,
  status TEXT CHECK (status IN ('pending','paid')) NOT NULL DEFAULT 'pending',
  paid_at TIMESTAMPTZ NULL,
  recorded_by UUID NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_payroll_employee FOREIGN KEY(employee_id) REFERENCES profiles(id),
  CONSTRAINT fk_payroll_admin FOREIGN KEY(recorded_by) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.staff_tasks (
  id UUID PRIMARY KEY,
  assigned_to UUID NULL,
  assigned_role TEXT CHECK (assigned_role IN ('customer','admin','pharmacist','merchandiser','delivery')) NULL,
  title VARCHAR(220) NOT NULL,
  details TEXT NULL,
  due_at TIMESTAMPTZ NULL,
  status TEXT CHECK (status IN ('pending','in_progress','completed','cancelled')) NOT NULL DEFAULT 'pending',
  created_by UUID NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_task_assignee FOREIGN KEY(assigned_to) REFERENCES profiles(id) ON DELETE SET NULL,
  CONSTRAINT fk_task_creator FOREIGN KEY(created_by) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.attendance_records (
  id UUID PRIMARY KEY,
  employee_id UUID NOT NULL,
  clock_in TIMESTAMPTZ NOT NULL,
  clock_out TIMESTAMPTZ NULL,
  status TEXT CHECK (status IN ('pending','verified','rejected')) NOT NULL DEFAULT 'pending',
  verified_by UUID NULL,
  verified_at TIMESTAMPTZ NULL,
  admin_note TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_attendance_employee FOREIGN KEY(employee_id) REFERENCES profiles(id) ON DELETE CASCADE,
  CONSTRAINT fk_attendance_admin FOREIGN KEY(verified_by) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.staff_reports (
  id UUID PRIMARY KEY,
  staff_id UUID NOT NULL,
  attendance_id UUID NULL,
  report_date DATE NOT NULL,
  title VARCHAR(220) NOT NULL,
  details TEXT NOT NULL,
  status TEXT CHECK (status IN ('submitted','reviewed')) NOT NULL DEFAULT 'submitted',
  reviewed_by UUID NULL,
  reviewed_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_report_staff FOREIGN KEY(staff_id) REFERENCES profiles(id) ON DELETE CASCADE,
  CONSTRAINT fk_report_attendance FOREIGN KEY(attendance_id) REFERENCES attendance_records(id) ON DELETE SET NULL,
  CONSTRAINT fk_report_reviewer FOREIGN KEY(reviewed_by) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.activity_logs (
  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  actor_id UUID NULL,
  actor_role TEXT CHECK (actor_role IN ('customer','admin','pharmacist','merchandiser','delivery')) NOT NULL,
  action VARCHAR(120) NOT NULL,
  entity_type VARCHAR(100) NOT NULL,
  entity_id UUID NULL,
  details JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_activity_actor FOREIGN KEY(actor_id) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.stock_deliveries (
  id UUID PRIMARY KEY,
  branch_id UUID NOT NULL,
  supplier_id UUID NULL,
  assigned_to UUID NULL,
  arranged_by UUID NULL,
  delivery_reference VARCHAR(120) NULL,
  expected_delivery_date DATE NOT NULL,
  status TEXT CHECK (status IN ('draft','scheduled','arrived','receiving','completed','cancelled')) NOT NULL DEFAULT 'scheduled',
  notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_stock_delivery_branch FOREIGN KEY(branch_id) REFERENCES branches(id) ON DELETE CASCADE,
  CONSTRAINT fk_stock_delivery_supplier FOREIGN KEY(supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL,
  CONSTRAINT fk_stock_delivery_assignee FOREIGN KEY(assigned_to) REFERENCES profiles(id) ON DELETE SET NULL,
  CONSTRAINT fk_stock_delivery_arranger FOREIGN KEY(arranged_by) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE TABLE public.stock_delivery_items (
  id UUID PRIMARY KEY,
  delivery_id UUID NOT NULL,
  product_id UUID NOT NULL,
  manufacturer_id UUID NULL,
  batch_number VARCHAR(100) NULL,
  expiration_date DATE NULL,
  expected_quantity INT NOT NULL,
  received_quantity INT NOT NULL DEFAULT 0,
  cost_per_unit DECIMAL(12,2) NOT NULL DEFAULT 0,
  receiving_note TEXT NULL,
  status TEXT CHECK (status IN ('pending','received','short','damaged','cancelled')) NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_stock_delivery_item_delivery FOREIGN KEY(delivery_id) REFERENCES stock_deliveries(id) ON DELETE CASCADE,
  CONSTRAINT fk_stock_delivery_item_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
  CONSTRAINT fk_stock_delivery_item_manufacturer FOREIGN KEY(manufacturer_id) REFERENCES manufacturers(id) ON DELETE SET NULL
);


-- A fresh database can enforce these invariants from day one.
ALTER TABLE public.branch_inventory
  ADD CONSTRAINT inventory_nonnegative CHECK (on_hand >= 0 AND reserved >= 0 AND reorder_level >= 0);
ALTER TABLE public.stock_delivery_items
  ADD CONSTRAINT delivery_item_quantities CHECK (expected_quantity > 0 AND received_quantity >= 0 AND cost_per_unit >= 0);
ALTER TABLE public.product_batches
  ADD CONSTRAINT batch_quantities CHECK (quantity_received >= 0 AND quantity_remaining >= 0 AND cost_per_unit >= 0);
ALTER TABLE public.orders
  ADD CONSTRAINT order_amounts_nonnegative CHECK (subtotal >= 0 AND discount_amount >= 0 AND delivery_fee >= 0 AND total_amount >= 0);

CREATE INDEX idx_profiles_role ON public.profiles (role,is_active);

CREATE INDEX idx_products_category ON public.products (category_id);

CREATE INDEX idx_products_manufacturer ON public.products (manufacturer_id);

CREATE INDEX idx_inventory_product ON public.branch_inventory (product_id);

CREATE INDEX idx_batches_expiry ON public.product_batches (expiration_date,branch_id);

CREATE INDEX idx_prescription_status ON public.prescriptions (status,created_at);

CREATE INDEX idx_consult_status ON public.consultations (status,created_at);

CREATE INDEX idx_order_customer ON public.orders (customer_id,created_at);

CREATE INDEX idx_order_status ON public.orders (status,created_at);

CREATE INDEX idx_payment_status ON public.payments (status,paid_at);

CREATE INDEX idx_attendance_employee ON public.attendance_records (employee_id,clock_in);

CREATE INDEX idx_attendance_status ON public.attendance_records (status,clock_in);

CREATE INDEX idx_staff_reports_status ON public.staff_reports (status,created_at);

CREATE INDEX idx_staff_reports_staff ON public.staff_reports (staff_id,report_date);

CREATE INDEX idx_activity_created ON public.activity_logs (created_at);


-- Tables deliberately have no exposed client-side RLS policies.
-- Only the FastAPI backend should access them using a server-side DATABASE_URL.
DO $pharmacy$
DECLARE item RECORD;
BEGIN
  FOR item IN SELECT tablename FROM pg_tables WHERE schemaname='public'
   AND tablename = ANY(ARRAY['profiles','branches','categories','manufacturers','suppliers','products','branch_inventory','stock_receipts','product_batches','stock_movements','promotions','promotion_products','favorites','customer_addresses','prescriptions','consultations','consultation_messages','orders','order_items','payments','deliveries','order_status_history','operating_expenses','payroll_entries','staff_tasks','attendance_records','staff_reports','activity_logs','stock_deliveries','stock_delivery_items'])
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', item.tablename);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', item.tablename);
  END LOOP;
END
$pharmacy$;



CREATE FUNCTION public.pharmacy360_touch_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;


CREATE TRIGGER trg_profiles_updated_at BEFORE UPDATE ON public.profiles
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_branches_updated_at BEFORE UPDATE ON public.branches
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_categories_updated_at BEFORE UPDATE ON public.categories
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_manufacturers_updated_at BEFORE UPDATE ON public.manufacturers
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_suppliers_updated_at BEFORE UPDATE ON public.suppliers
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_products_updated_at BEFORE UPDATE ON public.products
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_branch_inventory_updated_at BEFORE UPDATE ON public.branch_inventory
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_stock_receipts_updated_at BEFORE UPDATE ON public.stock_receipts
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_product_batches_updated_at BEFORE UPDATE ON public.product_batches
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_promotions_updated_at BEFORE UPDATE ON public.promotions
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_customer_addresses_updated_at BEFORE UPDATE ON public.customer_addresses
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_prescriptions_updated_at BEFORE UPDATE ON public.prescriptions
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_consultations_updated_at BEFORE UPDATE ON public.consultations
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_orders_updated_at BEFORE UPDATE ON public.orders
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_payments_updated_at BEFORE UPDATE ON public.payments
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_deliveries_updated_at BEFORE UPDATE ON public.deliveries
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_operating_expenses_updated_at BEFORE UPDATE ON public.operating_expenses
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_payroll_entries_updated_at BEFORE UPDATE ON public.payroll_entries
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_staff_tasks_updated_at BEFORE UPDATE ON public.staff_tasks
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_attendance_records_updated_at BEFORE UPDATE ON public.attendance_records
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_staff_reports_updated_at BEFORE UPDATE ON public.staff_reports
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_stock_deliveries_updated_at BEFORE UPDATE ON public.stock_deliveries
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();

CREATE TRIGGER trg_stock_delivery_items_updated_at BEFORE UPDATE ON public.stock_delivery_items
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_touch_updated_at();



-- Supabase Auth creates the identity; the app creates a customer-only profile.
-- Supabase user_metadata is NEVER trusted for staff roles.
CREATE OR REPLACE FUNCTION public.pharmacy360_new_auth_profile()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  INSERT INTO public.profiles(id, email, full_name, role, is_active)
  VALUES (NEW.id, NEW.email,
    LEFT(COALESCE(NEW.raw_user_meta_data ->> 'full_name', ''),160),
    'customer', TRUE)
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;

CREATE TRIGGER pharmacy360_auth_user_created
AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_new_auth_profile();

-- Storage: public medicine photos, private prescriptions.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES
  ('product-images','product-images',TRUE,5242880,ARRAY['image/jpeg','image/png','image/webp']),
  ('prescriptions','prescriptions',FALSE,10485760,ARRAY['application/pdf','image/jpeg','image/png','image/webp'])
ON CONFLICT (id) DO NOTHING;

COMMIT;
