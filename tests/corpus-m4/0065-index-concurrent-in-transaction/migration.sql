BEGIN; CREATE INDEX CONCURRENTLY users_amount ON public.users (amount); COMMIT;
