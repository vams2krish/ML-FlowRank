const {defineConfig}=require('@playwright/test');
module.exports=defineConfig({testDir:'./tests/browser',timeout:45000,use:{baseURL:process.env.BASE_URL||'http://127.0.0.1:8000',headless:true},reporter:'list',workers:1});
