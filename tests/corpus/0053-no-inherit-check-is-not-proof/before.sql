CREATE TABLE ss_m3_0053.items (id integer NOT NULL, body text);
ALTER TABLE ss_m3_0053.items ADD CONSTRAINT proof CHECK (body IS NOT NULL) NO INHERIT;
INSERT INTO ss_m3_0053.items VALUES (1, 'synthetic');
