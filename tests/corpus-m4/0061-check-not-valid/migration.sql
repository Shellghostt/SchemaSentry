ALTER TABLE public.users ADD CONSTRAINT amount_positive CHECK (amount > 0) NOT VALID;
