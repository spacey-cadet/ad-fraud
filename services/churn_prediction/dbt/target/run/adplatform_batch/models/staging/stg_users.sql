
  
  create view "warehouse"."main"."stg_users__dbt_tmp" as (
    select
    user_id,
    device_type,
    signup_date
from "warehouse"."main"."users"
  );
